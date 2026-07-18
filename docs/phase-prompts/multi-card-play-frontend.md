# Phase prompt: multi-card play — frontend

## Where things stand
The backend and protocol already support playing several same-rank cards as
one turn action (see `docs/RULES.md` "Multi-card plays" and
`docs/WS_PROTOCOL.md`'s `{"action": "play", "cards": [...]}` shape). Nothing
in `frontend/` sends it. Right now every tap on a hand/face-up card in
`frontend/src/screens/GameScreen.jsx` (`playCard`, line ~139) fires an
instant single-card `{"action": "play", "card": spec}` — that's the entire
interaction model today. This phase adds the missing client half: a way to
select several same-rank cards and throw them together.

Read `docs/RULES.md`'s "Multi-card plays" section and the `play` sections of
`docs/WS_PROTOCOL.md` before starting.

## The UX decision this prompt is making — sanity check it before building
Today, tapping a card **instantly plays it**, no confirm step. That's fast
and it's the right default for the common case (a single-card play). Do
**not** change that default behavior — don't add a confirm step to normal
single-tap play, that would be a real regression to the game's whole feel.

Instead: add an explicit, opt-in **"Throw multiples" toggle** near the hand
row. Tapping it switches the hand/face-up rows from "tap = instant play" into
"tap = select," shows which cards are selected, and reveals a "Play N" button
to confirm (or a "Cancel" to back out to normal instant-tap mode with the
selection cleared). This was chosen over a hidden gesture (e.g. long-press)
because a toggle is visually discoverable — nobody has to be told a secret
gesture exists to find this feature during a live game with friends who
haven't read the rules doc.

If you (the person running this prompt) think a different interaction is
better, stop and reconsider before implementing — this is a real UX call,
not an arbitrary detail, and I'm not in a position to playtest it with your
group. But build *something* concrete rather than leaving it a placeholder.

## State additions (`GameScreen.jsx`)
```js
const [multiSelectMode, setMultiSelectMode] = useState(false)
const [selection, setSelection] = useState([]) // [{ spec, rect }]
```
- `selection` stores rect alongside spec (same pattern as `pendingTapRef`
  today) so the eventual flight animation has something to animate from.
- Entering multi-select mode: `setMultiSelectMode(true)`. Exiting (Cancel, or
  after a successful send): `setMultiSelectMode(false); setSelection([])`.

## Selection behavior
While `multiSelectMode` is true, tapping a card in the hand or face-up row
**toggles selection instead of calling `playCard`**:
- Tapping an unselected card adds it to `selection` — but only if its rank
  matches the rank of whatever's already selected (first tap sets the rank,
  everything after must match). This is a **selection-shape rule, not a
  legality check** — keep it distinct from the "never block a tap on
  legality — the server is the only judge" philosophy already stated in this
  file's comments (~line 135). Not matching rank isn't a rules judgment the
  server should be making for you; it's the same category of thing as the
  existing `dimmed` prop (obviously-not-actionable, client-side hint only).
  Implement it as: a card whose rank doesn't match the current selection's
  rank renders `dimmed` and its tap is a no-op while in multi-select mode,
  exactly like an out-of-turn/wrong-layer card is dimmed today.
- Tapping an already-selected card removes it.
- Selected cards need a new visual state — see CSS below.

## Confirm / cancel UI
In the hand row's header (`.hand-header`, next to the existing "Pick up
pile" button):
- Default (not in multi-select mode): show a new "Throw multiples" button
  (`.button--quiet`, matching the existing tiny/quiet button styles already
  in `App.css`) that calls `setMultiSelectMode(true)`.
- In multi-select mode: replace it with two buttons — "Cancel" (clears
  selection, exits mode) and "Play {N}" (disabled while `selection.length
  === 0`, styled `.button--gold` to match the power-card accent color,
  since this is the "power move" of the interaction).
- Confirming sends `{"action": "play", "cards": selection.map(s => s.spec)}`
  via the existing `sendAction` — **always the plural `cards` form**, even
  for a one-card selection. The backend treats a one-element `cards` group
  identically to the legacy `card` field (confirmed by
  `test_single_card_group_matches_play_card_behavior` in
  `backend/tests/test_multi_play.py`), so there's no need to special-case
  N=1 on the client.
- After sending, exit multi-select mode and clear `selection` immediately —
  don't wait for the server's response. If the play is rejected, the
  existing error toast (`onServerError`) surfaces the message same as today;
  the player re-enters multi-select and re-selects if they want to retry.
  (The backend does not echo back which card in a rejected group caused the
  problem — see the `_describe_error` comment in `game_ws.py` — so don't try
  to highlight a specific card on a multi-card rejection. Just show the
  toast text, which is already specific per the engine's own error message.)

## Motion layer — deliberately limited scope this phase
`runMotion` currently animates exactly one flying card per `play` event,
matched via `pendingTapRef`. Do **not** build simultaneous multi-card flight
animation in this phase — that's real animation work and not what's blocking
the rule from being usable.

Instead: when confirming a multi-card play, set `pendingTapRef.current` to
`{ spec: selection[0].spec, rect: selection[0].rect }` (the first selected
card — this matches the backend's `event.card`, which is documented as "the
first card of the group" specifically for this kind of backward
compatibility). The existing flight logic will animate that one card to the
pile exactly as it does today; the rest of the group will simply disappear
from the hand/face-up row when the new state snapshot arrives (no flight,
no crash, just an instant remove). That's an acceptable, honest limitation —
note it with a code comment, don't silently leave it unexplained.

## `Card.jsx` / CSS
- Add a `selected` boolean prop to `Card`, pushed onto the class list as
  `card--selected` (alongside the existing `dimmed`/`rejected`/`power`
  pattern at the top of the component).
- In `App.css`, add `.card--selected` near `.card--rejected`/`.card--power`
  — a distinct highlight (don't reuse the gold power-card glow or the red
  rejected glow, those already mean something specific; consider the
  `--safe` teal token used elsewhere for "legal/good" states, e.g. a solid
  border + subtle glow in that color).
- Style the new "Throw multiples" / "Cancel" / "Play {N}" buttons using the
  existing `.button`, `.button--quiet`, `.button--gold` classes already in
  `App.css` — don't invent a new button visual language for this.

## What NOT to touch this phase
- **Opponent rendering** (`OpponentSeat`) — face-up cards are already public
  and render fine; opponents playing multi-card groups need no client change
  beyond the motion-layer note above.
- **Blind row** — RULES.md is explicit multi-card plays don't apply to the
  blind phase. Don't add selection UI to `you-row--blind`.
- **Simultaneous multi-card flight animation** — explicitly deferred, see
  above.
- **Card art** — unrelated, separate phase, already integrated or pending
  per its own prompt.
- **`useGameSocket.js` / `sendAction`** — no protocol-transport changes
  needed, it already sends arbitrary action objects; only the payload shape
  changes, which happens in `GameScreen.jsx`.

## Testing
Visual pass at 390px (project standard), specifically:
- Default state unaffected: tapping a single hand card with multi-select OFF
  still plays instantly, exactly as before — this is the regression that
  matters most, check it first.
- Toggle "Throw multiples" on, select 2–3 same-rank cards (e.g. deal
  yourself three 6s in a local test game if needed), confirm "Play 3" sends
  and the pile updates with all three cards.
- While a same-rank selection is active, confirm a different-rank card
  renders dimmed and tapping it does nothing.
- "Cancel" clears the selection and returns hand taps to instant-play mode.
- Force a rejection (e.g. select cards that don't beat the pile) and confirm
  the toast shows the engine's specific message without crashing or leaving
  the UI stuck in a broken state.
- Face-up row: confirm the same toggle/select/confirm flow works there when
  `active_layer === 'face_up'` (hand is empty).

## Definition of done
- Single-card instant-tap play is unchanged and unregressed.
- A player can select and confirm a same-rank multi-card play from either
  the hand or face-up row, and it lands correctly per the backend's already
  -tested behavior.
- No changes outside `frontend/` (the rule and protocol are already done).
