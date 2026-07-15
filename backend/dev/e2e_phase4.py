"""Phase 4 end-to-end check: two real browsers against a live server.

Serves the production build from FastAPI (dist -> backend/static, the same
layout the Dockerfile creates) so this exercises the single-origin path that
actually ships, rather than the Vite dev-server + CORS path.

Run:  .venv/Scripts/python.exe backend/dev/e2e_phase4.py

Uses the locally installed Chrome (channel="chrome") because pulling
Playwright's bundled Chromium over this connection is not viable.
"""

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# Card suits print as ♥/♠ and the Windows console defaults to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
DIST = REPO / "frontend" / "dist"
STATIC = BACKEND / "static"
VIEWPORT = {"width": 390, "height": 844}

# Mirrors app/engine/cards.py + game.is_legal_play. Kept in sync deliberately:
# the test must know what a legal move is to make one, but the server stays
# the only judge — every assertion below checks the server's answer.
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
VALUE = {r: i + 2 for i, r in enumerate(RANKS)}
POWER = {"2", "7", "10", "J"}
SYMBOL = {"C": "♣", "D": "♦", "H": "♥", "S": "♠"}
# Mirrors rooms/manager.py: digits included, 0/O/1/I/L excluded for readability.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def rank_of(spec):
    return spec[:-1]


def pretty(spec):
    return f"{rank_of(spec)}{SYMBOL[spec[-1]]}"


def is_legal(spec, top, seven_pending):
    r = rank_of(spec)
    if r in POWER:
        return True
    if seven_pending:
        return VALUE[r] <= 7
    if top is None:
        return True
    return VALUE[r] > VALUE[rank_of(top)]  # strictly higher; equal needs a power card


class Results:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
        return bool(ok)

    def failed(self):
        return [r for r in self.rows if not r[1]]


R = Results()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_health(base, proc, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server died early, exit={proc.returncode}")
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    raise RuntimeError("server never became healthy")


class Client:
    """One browser context = one player, with its own WebSocket frame log."""

    def __init__(self, browser, label):
        self.label = label
        self.ctx = browser.new_context(
            viewport=VIEWPORT, is_mobile=True, has_touch=True, device_scale_factor=3
        )
        self.page = self.ctx.new_page()
        self.recv = []
        self.sent = []
        self.sockets = []
        self.page.on("websocket", self._on_ws)

    def _on_ws(self, ws):
        self.sockets.append(ws)
        ws.on("framereceived", lambda p: self.recv.append(p))
        ws.on("framesent", lambda p: self.sent.append(p))

    def state(self):
        """Newest server state snapshot this browser actually received."""
        for payload in reversed(self.recv):
            try:
                msg = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if msg.get("type") == "state":
                return msg["state"]
        return None

    def all_states(self):
        out = []
        for payload in self.recv:
            try:
                msg = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if msg.get("type") == "state":
                out.append(msg["state"])
        return out

    def wait_state(self, predicate, timeout=10, what=""):
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.state()
            if st and predicate(st):
                return st
            self.page.wait_for_timeout(120)
        raise AssertionError(f"{self.label}: timed out waiting for state: {what}")

    def card_labels(self):
        return self.page.eval_on_selector_all(
            ".card", "els => els.map(e => e.getAttribute('aria-label'))"
        )

    def token(self):
        return self.page.evaluate(
            "() => JSON.parse(sessionStorage.getItem('hsl-cards-session') || '{}').token || null"
        )


def main():
    if not DIST.is_dir():
        print("frontend/dist missing — run `npm run build` in frontend/ first")
        return 1

    print("== setup ==")
    if STATIC.exists():
        shutil.rmtree(STATIC)
    shutil.copytree(DIST, STATIC)
    print(f"  copied {DIST} -> {STATIC} (mirrors Dockerfile layout)")

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health(base, proc)
        print(f"  server live at {base}")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                run_scenario(browser, base)
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if STATIC.exists():
            shutil.rmtree(STATIC)  # keep the working tree clean

    print("\n== summary ==")
    bad = R.failed()
    print(f"  {len(R.rows) - len(bad)}/{len(R.rows)} checks passed")
    for name, _ok, detail in bad:
        print(f"  FAILED: {name} :: {detail}")
    return 1 if bad else 0


def run_scenario(browser, base):
    A = Client(browser, "A/host")
    B = Client(browser, "B/joiner")

    # ---------------------------------------------------------- lobby (REST)
    print("\n== 1. create / join / ready / start (REST) ==")
    A.page.goto(base)
    A.page.fill(".field-input", "Mustafa")
    A.page.click("text=Create a room")
    A.page.wait_for_selector("[data-testid=room-code]", timeout=15000)
    code = A.page.inner_text("[data-testid=room-code]").strip()
    R.check("host creates room, gets a code",
            len(code) == 5 and all(ch in CODE_ALPHABET for ch in code), f"code={code!r}")

    B.page.goto(base)
    B.page.fill(".field-input", "Ali")
    B.page.fill(".field-input--code", code)
    B.page.click("button:has-text('Join')")
    B.page.wait_for_selector("[data-testid=room-code]", timeout=15000)
    R.check("joiner reaches lobby by code", B.page.inner_text("[data-testid=room-code]").strip() == code)

    # Host must see player 2 appear with no reload -> proves the 2s poll.
    try:
        A.page.wait_for_function("() => document.querySelectorAll('.lobby-player').length === 2", timeout=10000)
        polled = True
    except PWTimeout:
        polled = False
    names_a = A.page.eval_on_selector_all(".lobby-player-name", "e => e.map(x => x.innerText)")
    R.check("lobby POLLING shows both players to host (no reload)", polled, f"host sees {names_a}")
    names_b = B.page.eval_on_selector_all(".lobby-player-name", "e => e.map(x => x.innerText)")
    R.check("lobby shows both players to joiner", len(names_b) == 2, f"joiner sees {names_b}")

    A.page.click("button:has-text(\"I'm ready\")")
    B.page.click("button:has-text(\"I'm ready\")")
    A.page.wait_for_function(
        "() => [...document.querySelectorAll('.ready')].length === 2 && "
        "[...document.querySelectorAll('.ready')].every(e => e.classList.contains('ready--yes'))",
        timeout=10000,
    )
    R.check("both players ready-up (visible to host via poll)", True)

    R.check("only host sees Start game", B.page.locator("button:has-text('Start game')").count() == 0)
    A.page.click("button:has-text('Start game')")

    # ------------------------------------------------------ websocket + auth
    print("\n== 2. websocket connect + token auth ==")
    A.page.wait_for_selector(".turn-banner", timeout=15000)
    B.page.wait_for_selector(".turn-banner", timeout=15000)  # joiner transitions via poll
    sa = A.wait_state(lambda s: True, what="A first snapshot")
    sb = B.wait_state(lambda s: True, what="B first snapshot")
    R.check("both browsers opened a WebSocket", len(A.sockets) == 1 and len(B.sockets) == 1,
            f"A={len(A.sockets)} B={len(B.sockets)}")

    for c in (A, B):
        first = json.loads(c.sent[0]) if c.sent else {}
        R.check(f"{c.label}: first frame is token auth", first.get("token") == c.token(),
                f"sent keys={list(first)}")
    R.check("both received a state snapshot", sa is not None and sb is not None)
    R.check("snapshot room_code matches", sa["room_code"] == code and sb["room_code"] == code)

    a_id, b_id = sa["you"]["player_id"], sb["you"]["player_id"]
    # 9 dealt as 3+3+3, PLUS the deck-phase auto-draw the engine performs for
    # whoever is on turn (_start_turn / WS_PROTOCOL.md: there is no draw action).
    for st, me in ((sa, a_id), (sb, b_id)):
        you = st["you"]
        drew = st["phase"] == "deck" and st["current_player_id"] == me
        total = len(you["hand"]) + len(you["face_up"]) + you["blind_count"]
        R.check(f"{'current' if drew else 'waiting'} player dealt 3+3+3{' +1 auto-draw' if drew else ''}",
                total == (10 if drew else 9) and len(you["face_up"]) == 3 and you["blind_count"] == 3,
                f"hand={len(you['hand'])} face_up={len(you['face_up'])} blind={you['blind_count']} total={total}")
    R.check("deck shrank by exactly the one auto-drawn card",
            sa["draw_deck_count"] == 52 - 18 - 1, f"draw_deck_count={sa['draw_deck_count']}")

    # ------------------------------------------------- filtered state (core)
    print("\n== 3. filtered state: A must never receive/render B's hidden cards ==")
    assert_filtered(A, B, a_id, b_id, "at deal")

    # ------------------------------------------- out-of-turn tap -> toast
    print("\n== 4. out-of-turn tap shows a toast, not a crash ==")
    cur = sa["current_player_id"]
    waiter, waiter_state = (B, sb) if cur == a_id else (A, sa)
    other = A if waiter is B else B
    R.check("server picked a current player", cur in (a_id, b_id), f"current={cur}")

    idle_card = waiter_state["you"]["hand"][0]
    waiter.page.click(f".you-row--hand .card[aria-label='{pretty(idle_card)}']")
    try:
        waiter.page.wait_for_selector(".toast[role=alert]", timeout=8000)
        toast_text = waiter.page.inner_text(".toast")
        toasted = True
    except PWTimeout:
        toast_text, toasted = "", False
    R.check("out-of-turn tap produces a visible toast", toasted, f"toast={toast_text!r}")
    R.check("out-of-turn tap did not crash the page (app still rendered)",
            waiter.page.locator(".turn-banner").count() == 1)
    R.check("out-of-turn tap mutated nothing (both still see same current player)",
            waiter.state()["current_player_id"] == cur and other.state()["current_player_id"] == cur)

    # ------------------------------------------------------- a real turn
    print("\n== 5. a full turn: play a card, both browsers update, turn moves ==")
    mover = A if cur == a_id else B
    watcher = B if mover is A else A
    st = mover.wait_state(lambda s: s["current_player_id"] == cur, what="mover snapshot")
    you = st["you"]
    R.check("mover is on their hand layer during deck phase", you["active_layer"] == "hand",
            f"active_layer={you['active_layer']} phase={st['phase']}")

    legal = [c for c in you["hand"] if is_legal(c, st["top_card"], st["seven_pending"])]
    R.check("mover has at least one legal play", len(legal) > 0,
            f"hand={you['hand']} top={st['top_card']} seven_pending={st['seven_pending']}")
    if not legal:
        return
    # Prefer a plain card, then a non-10 power card: a 10 burns the pile and
    # would make "top card is now X" untestable. 10 is handled below anyway.
    legal.sort(key=lambda c: (rank_of(c) in POWER, rank_of(c) == "10"))
    card = legal[0]
    print(f"  {mover.label} plays {card} onto top={st['top_card']}")

    mover.page.click(f".you-row--hand .card[aria-label='{pretty(card)}']")
    nxt = b_id if cur == a_id else a_id
    for c in (A, B):
        c.wait_state(lambda s: s["current_player_id"] == nxt, what=f"{c.label} sees turn advance")

    burned = rank_of(card) == "10"
    expected_top = None if burned else card
    for c in (A, B):
        s = c.state()
        R.check(f"{c.label}: server state top_card is correct after play",
                s["top_card"] == expected_top, f"top={s['top_card']} expected={expected_top}")
        R.check(f"{c.label}: turn advanced to the other player", s["current_player_id"] == nxt)

    if not burned:
        for c in (A, B):
            c.page.wait_for_selector(f".discard .card--lg[aria-label='{pretty(card)}']", timeout=8000)
            R.check(f"{c.label}: DOM discard pile shows {pretty(card)} on top", True)

    # Turn indicator moved in the actual DOM of both browsers.
    nxt_client = A if nxt == a_id else B
    prev_client = B if nxt == a_id else A
    # text_content(), not inner_text(): .turn-banner--you is styled
    # text-transform:uppercase, so the rendered text is "YOUR TURN" while the
    # DOM text is "Your turn". Assert the underlying text and the gold class.
    nxt_client.page.wait_for_selector(".turn-banner--you", timeout=8000)
    R.check("next player's DOM says 'Your turn' (gold --you banner)",
            nxt_client.page.text_content(".turn-banner").strip() == "Your turn"
            and nxt_client.page.locator(".turn-banner--you").count() == 1,
            f"banner={nxt_client.page.text_content('.turn-banner')!r} "
            f"rendered={nxt_client.page.inner_text('.turn-banner')!r}")
    prev_text = prev_client.page.text_content(".turn-banner").strip()
    R.check("previous player's DOM no longer says 'Your turn'",
            "Your turn" not in prev_text and prev_client.page.locator(".turn-banner--you").count() == 0,
            f"banner={prev_text!r}")

    R.check("both browsers reflect the same public pile", A.state()["discard_pile"] == B.state()["discard_pile"],
            f"A={A.state()['discard_pile']} B={B.state()['discard_pile']}")

    print("\n== 6. filtered state re-checked after a play ==")
    assert_filtered(A, B, a_id, b_id, "after play")

    # ------------------------------------------------------------ reconnect
    print("\n== 7. reload reconnects via stored token and resumes ==")
    before = A.state()
    sockets_before = len(A.sockets)
    A.page.reload()
    A.page.wait_for_selector(".turn-banner", timeout=15000)
    A.wait_state(lambda s: True, what="A post-reload snapshot")
    after = A.state()
    R.check("reload opened a NEW websocket (reconnected)", len(A.sockets) > sockets_before,
            f"{sockets_before} -> {len(A.sockets)}")
    R.check("reload resumed the same room/player", after["room_code"] == code and after["you"]["player_id"] == a_id)
    R.check("reload restored the correct game state (same pile + turn)",
            after["discard_pile"] == before["discard_pile"]
            and after["current_player_id"] == before["current_player_id"],
            f"pile {before['discard_pile']} -> {after['discard_pile']}")
    R.check("reload restored A's own hand exactly", sorted(after["you"]["hand"]) == sorted(before["you"]["hand"]))
    R.check("A landed back in the game, not the entry screen",
            A.page.locator(".entry-title").count() == 0 and A.page.locator(".game").count() == 1)
    assert_filtered(A, B, a_id, b_id, "after reload")


def assert_filtered(A, B, a_id, b_id, when):
    """The heart of it: A's browser must never learn B's private cards."""
    sa, sb = A.state(), B.state()

    # 1. Structural: A's payload has no hand/blind values for anyone else.
    leaks = []
    for st, me, label in ((sa, a_id, "A"), (sb, b_id, "B")):
        for pl in st["players"]:
            if pl["player_id"] == me:
                continue
            for key in ("hand", "blind", "blind_cards"):
                if key in pl:
                    leaks.append(f"{label}.players[{pl['name']}].{key}={pl[key]}")
    R.check(f"({when}) opponent entries expose counts only, never card values", not leaks, "; ".join(leaks))

    # 2. Blind cards are never sent to anyone — not even their owner.
    R.check(f"({when}) own blind layer is a count, never values",
            "blind" not in sa["you"] and isinstance(sa["you"]["blind_count"], int),
            f"you keys={sorted(sa['you'])}")

    # 3. The real one: B's private hand must not appear anywhere in ANY frame
    #    A received. Single 52-card deck => every spec is unique, so a card in
    #    B's hand cannot legitimately appear in A's view at all.
    b_hand = set(sb["you"]["hand"])
    a_visible = set(sa["discard_pile"]) | set(sa["you"]["hand"]) | set(sa["you"]["face_up"])
    if sa["top_card"]:
        a_visible.add(sa["top_card"])
    for pl in sa["players"]:
        a_visible |= set(pl["face_up"])
    overlap = b_hand & a_visible
    R.check(f"({when}) B's hand appears nowhere in A's current state", not overlap, f"leaked={sorted(overlap)}")

    a_hand = set(sa["you"]["hand"])
    b_visible = set(sb["discard_pile"]) | set(sb["you"]["hand"]) | set(sb["you"]["face_up"])
    if sb["top_card"]:
        b_visible.add(sb["top_card"])
    for pl in sb["players"]:
        b_visible |= set(pl["face_up"])
    R.check(f"({when}) A's hand appears nowhere in B's current state", not (a_hand & b_visible),
            f"leaked={sorted(a_hand & b_visible)}")

    # 4. Historical sweep: across every frame A ever received.
    hist = set()
    for st in A.all_states():
        hist |= set(st["discard_pile"]) | set(st["you"]["hand"]) | set(st["you"]["face_up"])
        for pl in st["players"]:
            hist |= set(pl["face_up"])
    still_hidden = b_hand - set(sb["you"]["face_up"])
    R.check(f"({when}) B's current hand never leaked in A's frame history",
            not (still_hidden & hist), f"leaked={sorted(still_hidden & hist)}")

    # 5. DOM: nothing B holds is rendered in A's page.
    labels_a = [l for l in A.card_labels() if l]
    bad = sorted({c for c in b_hand if pretty(c) in labels_a})
    R.check(f"({when}) A's DOM renders none of B's hand cards", not bad,
            f"leaked={bad} labels={labels_a}")

    # 6. A's view of B's face-down cards is backs only, matching the count.
    b_seat = next(p for p in sa["players"] if p["player_id"] == b_id)
    R.check(f"({when}) A sees B's hand as a count only",
            isinstance(b_seat["hand_count"], int) and b_seat["hand_count"] == len(sb["you"]["hand"]),
            f"A sees hand_count={b_seat['hand_count']}, B really holds {len(sb['you']['hand'])}")


if __name__ == "__main__":
    sys.exit(main())
