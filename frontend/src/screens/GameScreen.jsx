import { useEffect, useRef, useState } from 'react'
// The "light" ESM build: SVG renderer only, and — the reason it's worth
// naming explicitly — no expression evaluator, so no `eval` in the bundle.
// fire.json uses neither, and the full player costs ~250kB more.
import lottie from 'lottie-web/build/player/esm/lottie_light.min.js'
import Card from '../components/Card.jsx'
import { useGameSocket } from '../hooks/useGameSocket.js'
import { parseCard, prettyCard, sortHand } from '../cards.js'
import fireAnimation from '../assets/animations/fire.json'

// Once a turn has been stalled this long, everyone gets told who the table
// is waiting on — otherwise the eventual forced pickup/flip/skip looks like
// a glitch to the other players.
const STALL_WARNING_SECONDS = 12
const URGENT_SECONDS = 7

// Flight/burn/flash durations live in App.css; these only bound how long the
// transient DOM for each effect sticks around. Generous on purpose — removal
// a beat late is invisible, removal a beat early truncates the animation.
const FLIGHT_CLEANUP_MS = 450
// fire.json is 30 frames at 30fps — exactly 1s of flame — and the burned
// card's pop tail runs the ~160ms after that. Paired with the 1.16s
// `burn-away` animation in App.css; move one and move the other.
const FIRE_MS = 1000
const BURN_CLEANUP_MS = FIRE_MS + 160
const FORCED_FLASH_MS = 900

// A blind flip is the one moment the table learns a card nobody knew —
// including its owner — so it gets held big and centred before the pile
// resolution runs. Long enough to read across a room on a phone; the
// reduced-motion hold is shorter because the information (not the beat) is
// what those users still need.
const BLIND_REVEAL_MS = 2000
const BLIND_REVEAL_REDUCED_MS = 900

// A chat bubble pops over the sender's seat and fades. Short on purpose:
// the drawer is the record, the bubble is only the "who just said
// something" glance. Reduced motion keeps the same hold — unlike the blind
// reveal, nothing here is information the table can't get elsewhere, so
// there's no reason to shorten it, only to stop it moving.
const CHAT_BUBBLE_MS = 2500
// Mirrors the server cap (docs/WS_PROTOCOL.md "Chat"); the server is still
// the one enforcing it.
const CHAT_MAX_LENGTH = 240
// The server keeps 50; the client can afford a longer scrollback across a
// session, since chat_history only ever re-seeds the newest 50.
const CHAT_LOG_MAX = 100
const QUICK_EMOJI = ['😂', '🔥', '😱', '👏', '😤', '💀', '🤔', '🤝']

// A one-glyph message IS a reaction (no separate action type on the wire —
// see WS_PROTOCOL.md), so it's detected rather than flagged: at most two
// code points and no alphanumerics. Spread, not .length, so a surrogate
// pair counts as one character.
const isReaction = (text) => [...text].length <= 2 && !/[a-z0-9]/i.test(text)

// 2 / 7 / J pile reactions. The ring and glyph animations are under a
// second; the 7's badge deliberately outlives its ripple so the rank
// ceiling is still readable while the next player decides.
const POWER_FX_MS = 950
const SEVEN_BADGE_MS = 3200

// The fire is drawn into a square this many times the pile card's height —
// the flames need room to lick past the card's edges instead of being
// clipped to it. FIRE_BASE is where the flame's root sits inside fire.json's
// own 500×500 frame (its layers are anchored at y≈460), so the box is hung
// from that point rather than centred: the fire then rises FROM the card
// instead of straddling it with half the flame below the table.
const FIRE_SCALE = 2.2
const FIRE_BASE = 0.92

// One-time dealing animation (fresh match start only). One ghost launches
// per step; land fires when the flight visually arrives (transform
// transition is 0.3s in App.css), cleanup removes the faded ghost.
const DEAL_STEP_MS = 90
const DEAL_LAND_MS = 260
const DEAL_CLEANUP_MS = 450

// Seat ellipse, in % of the .round-table box. RX < RY because seats are
// wider than they are tall — this keeps side seats off the center hub
// while top/bottom seats clear the table edges.
const SEAT_RX = 34
const SEAT_RY = 38

// k = 0 is the bottom of the table (your own anchor); increasing k walks
// CLOCKWISE on screen, matching direction === 1 walking the players array
// forward. Screen y grows downward, so cos/sin of an increasing angle
// traces right → bottom → left, which IS clockwise.
const seatAngle = (k, count) => Math.PI / 2 + (2 * Math.PI * k) / count
const seatPos = (k, count) => {
  const a = seatAngle(k, count)
  return {
    left: `${50 + SEAT_RX * Math.cos(a)}%`,
    top: `${50 + SEAT_RY * Math.sin(a)}%`,
  }
}

const DEAL_CARD_DIMS = { xs: { w: 24, h: 34 }, sm: { w: 42, h: 58 }, md: { w: 52, h: 74 } }

// Most cards in one fan row before the hand wraps to a second row.
const HAND_ROW_MAX = 6

const rectOf = (el) => {
  if (!el) return null
  const { x, y, width, height } = el.getBoundingClientRect()
  return { x, y, w: width, h: height }
}

export default function GameScreen({ session, dealOnEntry, onLeave, onFatalClose }) {
  // { message, code, card } — see docs/WS_PROTOCOL.md.
  const [error, setError] = useState(null)
  const [lastEvent, setLastEvent] = useState(null)
  const toastTimer = useRef(null)

  // Opt-in "Throw multiples" mode: while on, hand/face-up taps toggle
  // selection instead of playing instantly. Entries keep the tapped
  // element's rect (same reason as pendingTapRef — the flight animation
  // needs a start point) plus a row-positional id, so two copies of the
  // same card in a two-deck game stay individually selectable.
  const [multiSelectMode, setMultiSelectMode] = useState(false)
  const [selection, setSelection] = useState([]) // [{ id, spec, rect }]

  // Transient motion layer: cards mid-flight to the pile, the burn ghost of
  // a just-nuked pile, and the danger flash on whoever the AFK timer moved
  // for. All render as fixed-position overlays (pointer-events: none), so
  // nothing here ever blocks the next tap.
  const [flights, setFlights] = useState([])
  const [burn, setBurn] = useState(null)
  const [forcedFlash, setForcedFlash] = useState(null)
  // { rank, id } for the 2/7/J beats — one at a time, since only one card
  // can be the newly played top card. The 7's "≤7" badge is separate state
  // because it outlives the ripple that introduces it.
  const [powerFx, setPowerFx] = useState(null)
  const [ruleBadge, setRuleBadge] = useState(null)
  // { id, card, playerId } of the blind flip currently being shown, plus the
  // FIFO of flips still waiting their turn. Unlike burn/powerFx (which
  // clobber each other on a timestamp key), reveals must never be skipped:
  // a chained flip whose reveal got dropped is a card the table never saw.
  const [blindReveal, setBlindReveal] = useState(null)

  // Chat. `chatLog` is the record (seeded by chat_history on every connect,
  // appended to by chat), `bubbles` is the transient over-the-seat layer,
  // and `unread` counts what arrived while the drawer was shut.
  const [chatLog, setChatLog] = useState([])
  const [chatOpen, setChatOpen] = useState(false)
  const [bubbles, setBubbles] = useState([])
  const [unread, setUnread] = useState(0)
  const [chatDraft, setChatDraft] = useState('')
  // Read inside the socket handler, which must see the value as of the
  // message — not as of the render that installed the handler.
  const chatOpenRef = useRef(chatOpen)
  chatOpenRef.current = chatOpen
  // One timer per live bubble (several players can talk at once), all
  // cleared together on unmount like every other effect timer here.
  const bubbleTimers = useRef(new Set())
  const chatListRef = useRef(null)

  const revealQueue = useRef([])
  const revealBusy = useRef(false)
  const revealSeq = useRef(0)
  const revealTimer = useRef(null)
  const discardRef = useRef(null)
  const blindRowRef = useRef(null)
  const faceUpRowRef = useRef(null)
  const youAreaRef = useRef(null)
  const seatRefs = useRef({})
  const pendingTapRef = useRef(null) // { spec, rect } of the card just tapped
  const burnTimer = useRef(null)
  const flashTimer = useRef(null)
  const powerFxTimer = useRef(null)
  const ruleBadgeTimer = useRef(null)

  // One-time dealing animation. `dealOnEntry` is read once at mount: it is
  // only true on the lobby's "match just started" path, never on a
  // reload/reconnect. While `dealing`, seat stacks and your own rows render
  // clamped to how many cards have visually landed so far; the real state
  // underneath never changes.
  const [dealing, setDealing] = useState(() => Boolean(dealOnEntry))
  const dealingRef = useRef(dealing)
  const [dealGhosts, setDealGhosts] = useState([])
  const [dealLanded, setDealLanded] = useState(0)
  const dealScript = useRef(null)
  const dealLaunched = useRef(0)
  const dealTimer = useRef(null)
  const deckRef = useRef(null)
  const handRowRef = useRef(null)

  const endDeal = () => {
    clearInterval(dealTimer.current)
    dealingRef.current = false
    setDealing(false)
    setDealGhosts([])
  }

  const resolveMotion = (event, state) => {
    const to = rectOf(discardRef.current)
    if (!to) return
    const myId = state.you.player_id

    if ((event.kind === 'play' || event.kind === 'flip') && event.pile_burned) {
      // A nuke gets its own bigger beat instead of the normal flight: the 10
      // lands on the pile, real fire burns over it, and the card pops out as
      // the flames finish. Timestamp key so back-to-back burns (rare, but
      // legal) each remount the ghost and restart the fire.
      setBurn({ id: Date.now(), spec: event.card, rect: to })
      clearTimeout(burnTimer.current)
      burnTimer.current = setTimeout(() => setBurn(null), BURN_CLEANUP_MS)
    } else if (event.kind === 'play' || (event.kind === 'flip' && event.played)) {
      let from
      if (event.player_id !== myId) {
        from = rectOf(seatRefs.current[event.player_id])
      } else if (event.kind === 'flip') {
        from = rectOf(blindRowRef.current)
      } else if (pendingTapRef.current?.spec === event.card) {
        from = pendingTapRef.current.rect
      } else {
        // Our play but no matching tap (e.g. this tab was reclaimed after a
        // play from another device) — fall back to the hand area.
        from = rectOf(youAreaRef.current)
      }
      if (from) {
        setFlights((cur) => [
          // cap concurrent ghosts; stale ones are already invisible
          ...cur.slice(-2),
          { id: `${event.card}-${Date.now()}`, spec: event.card, from, to },
        ])
      }
    } else if (event.kind === 'flip' && event.picked_up) {
      // The mirror image of a play: the flipped card didn't beat the pile,
      // so the same ghost flies the other way — off the pile and into
      // whoever flipped it. Destination is a card-sized box centred on their
      // area (the raw rect is a whole panel/seat, which would anchor the
      // ghost at its corner), sized to match the pile card so the flight
      // reads as travel rather than a resize.
      const target =
        event.player_id === myId
          ? rectOf(youAreaRef.current)
          : rectOf(seatRefs.current[event.player_id])
      if (target) {
        const dest = {
          x: target.x + target.w / 2 - to.w / 2,
          y: target.y + target.h / 2 - to.h / 2,
          w: to.w,
          h: to.h,
        }
        setFlights((cur) => [
          ...cur.slice(-2),
          { id: `${event.card}-back-${Date.now()}`, spec: event.card, from: to, to: dest },
        ])
      }
    }
    pendingTapRef.current = null

    // 2 / 7 / J each get a beat on the table itself, on top of (not instead
    // of) the normal flight — the card still visibly travels to the pile
    // while the pile, badge, or direction ring reacts to what it did. Flips
    // count too: a blind-flipped J reverses the table just as hard as a
    // played one. The 10 is handled by the burn branch above.
    const played = event.kind === 'play' || (event.kind === 'flip' && event.played)
    if (played && !event.pile_burned) {
      const { rank } = parseCard(event.card)
      if (rank === '2' || rank === '7' || rank === 'J') {
        setPowerFx({ rank, id: Date.now() })
        clearTimeout(powerFxTimer.current)
        powerFxTimer.current = setTimeout(() => setPowerFx(null), POWER_FX_MS)
      }
      if (rank === '7') {
        setRuleBadge({ id: Date.now(), text: '≤ 7' })
        clearTimeout(ruleBadgeTimer.current)
        ruleBadgeTimer.current = setTimeout(() => setRuleBadge(null), SEVEN_BADGE_MS)
      }
    }

    if (event.forced) {
      setForcedFlash({ playerId: event.player_id })
      clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setForcedFlash(null), FORCED_FLASH_MS)
    }
  }

  // Show the head of the reveal queue, and only once its hold is over let
  // that flip resolve into the pile motion — then immediately start the next
  // one. Chained flips (a flipped 2 arms another flip) therefore play out as
  // reveal → resolve → reveal → resolve, never overlapping.
  const startNextReveal = () => {
    const next = revealQueue.current.shift()
    if (!next) {
      revealBusy.current = false
      setBlindReveal(null)
      return
    }
    revealBusy.current = true
    const { event, state } = next
    revealSeq.current += 1
    setBlindReveal({ id: revealSeq.current, card: event.card, playerId: event.player_id })
    const hold = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      ? BLIND_REVEAL_REDUCED_MS
      : BLIND_REVEAL_MS
    revealTimer.current = setTimeout(() => {
      resolveMotion(event, state)
      startNextReveal()
    }, hold)
  }

  const runMotion = (event, state) => {
    if (event.kind === 'flip') {
      revealQueue.current.push({ event, state })
      if (!revealBusy.current) startNextReveal()
      return
    }
    resolveMotion(event, state)
  }

  const { gameState, status, sendAction, reclaim } = useGameSocket(session.roomCode, session.token, {
    onServerError: (payload) => {
      clearTimeout(toastTimer.current)
      setError(payload)
      toastTimer.current = setTimeout(() => setError(null), 4000)
    },
    onEvent: (event, state) => {
      // A real move landed while the dealing animation was still running
      // (an eager player acted fast). The animation is pure decoration over
      // already-final state, so cancel it and snap to reality — nothing is
      // lost, and the event's own motion below plays normally.
      if (dealingRef.current) endDeal()
      setLastEvent(event)
      // The table moved, so any complaint about the old state is stale —
      // drop it rather than leave a card marked against a pile it no
      // longer refers to.
      clearTimeout(toastTimer.current)
      setError(null)
      runMotion(event, state)
    },
    onChat: (entry) => {
      setChatLog((cur) => [...cur, entry].slice(-CHAT_LOG_MAX))
      if (!chatOpenRef.current) setUnread((n) => n + 1)

      // Anchor rect is captured now, the same way flights capture theirs:
      // the bubble is a fixed-position overlay, so it needs a position, not
      // a live element. A seat that can't be measured just gets no bubble —
      // the message is still in the log either way.
      const mine = entry.player_id === session.playerId
      const rect = mine ? rectOf(youAreaRef.current) : rectOf(seatRefs.current[entry.player_id])
      if (!rect) return
      // Your own bubble sits above the you-area (the screen's bottom edge is
      // right below it); opponents' hang below their seat, because the seat
      // arc is at the TOP of the table and a bubble above it would land on
      // the turn banner. Either way it points at the speaker over empty felt.
      setBubbles((cur) => [
        ...cur,
        { id: entry.id, x: rect.x + rect.w / 2, y: mine ? rect.y : rect.y + rect.h, below: !mine, text: entry.text },
      ])
      const timer = setTimeout(() => {
        bubbleTimers.current.delete(timer)
        setBubbles((cur) => cur.filter((b) => b.id !== entry.id))
      }, CHAT_BUBBLE_MS)
      bubbleTimers.current.add(timer)
    },
    // Replaces rather than merges: the backlog is authoritative and arrives
    // on every (re)connect, so merging would duplicate the tail.
    onChatHistory: (messages) => setChatLog(messages.slice(-CHAT_LOG_MAX)),
    onFatalClose,
  })

  useEffect(
    () => () => {
      clearTimeout(toastTimer.current)
      clearTimeout(burnTimer.current)
      clearTimeout(flashTimer.current)
      clearTimeout(powerFxTimer.current)
      clearTimeout(ruleBadgeTimer.current)
      clearTimeout(revealTimer.current)
      clearInterval(dealTimer.current)
      bubbleTimers.current.forEach(clearTimeout)
      bubbleTimers.current.clear()
    },
    []
  )

  // Follow the conversation: a message arriving while the drawer is open
  // should be visible without scrolling for it.
  useEffect(() => {
    if (!chatOpen) return
    const list = chatListRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [chatOpen, chatLog])

  // The phone back gesture must close the chat drawer, NOT navigate away.
  // While the drawer is open we own one history entry: opening pushes it, a
  // back gesture pops it (popstate → just close the drawer, the navigation
  // is spent on our entry instead of falling through to leave the page and
  // tear down the socket), and closing via the in-app button consumes it so
  // the stack can't grow across repeated open/close cycles.
  useEffect(() => {
    if (!chatOpen) return undefined
    window.history.pushState({ chatOpen: true }, '')
    const onPop = () => setChatOpen(false)
    window.addEventListener('popstate', onPop)
    return () => {
      window.removeEventListener('popstate', onPop)
      // Closed by the button (not by back): our entry is still current, so
      // pop it ourselves. After a back gesture the entry is already gone —
      // history.state no longer carries our marker — so we leave it alone.
      if (window.history.state?.chatOpen) window.history.back()
    }
  }, [chatOpen])

  // Build the deal script off the first snapshot (all counts/cards are
  // already final — the server dealt everything in one shot at start), then
  // launch one ghost per DEAL_STEP_MS. Round-robin: each layer, three
  // rounds, one card per seat per round — the classic hand-deal order.
  // Restartable by design (launch index lives in a ref, cleanup only stops
  // the timer), so StrictMode remounts and mid-deal snapshots just resume.
  useEffect(() => {
    if (!dealing || !gameState) return undefined
    if (!dealScript.current) {
      const yourId = gameState.you.player_id
      const script = []
      for (const layer of ['blind', 'face_up', 'hand']) {
        for (let round = 0; round < 3; round++) {
          for (const p of gameState.players) {
            if (layer === 'blind' && round < p.blind_count) {
              script.push({ pid: p.player_id, layer, spec: null, seed: `${p.player_id}:${round}` })
            } else if (layer === 'face_up' && round < p.face_up.length) {
              script.push({ pid: p.player_id, layer, spec: p.face_up[round] })
            } else if (layer === 'hand' && round < Math.min(p.hand_count, 3)) {
              // Only your own hand flies face-up — it's the only hand you
              // can see. gameState.you.hand is unsorted here on purpose:
              // this is the "as dealt" order the ghosts should follow.
              script.push({
                pid: p.player_id,
                layer,
                spec: p.player_id === yourId ? gameState.you.hand[round] : null,
              })
            }
          }
        }
      }
      dealScript.current = script
    }

    const yourId = gameState.you.player_id
    dealTimer.current = setInterval(() => {
      const script = dealScript.current
      if (dealLaunched.current >= script.length) {
        clearInterval(dealTimer.current)
        return
      }
      const entry = script[dealLaunched.current]
      dealLaunched.current += 1

      const toYou = entry.pid === yourId
      // Your ring seat no longer exists — your dealt cards land straight in
      // the matching you-area row; opponents' land on their seat marker.
      const yourRowFor = { blind: blindRowRef, face_up: faceUpRowRef, hand: handRowRef }
      const size = !toYou ? 'xs' : entry.layer === 'hand' ? 'md' : 'sm'
      const from = rectOf(deckRef.current)
      const target = toYou
        ? rectOf(yourRowFor[entry.layer].current)
        : rectOf(seatRefs.current[entry.pid])
      if (!from || !target) {
        // Can't animate this one (seat not measurable) — count it landed so
        // the sequence still completes.
        setDealLanded((n) => n + 1)
        return
      }
      const dims = DEAL_CARD_DIMS[size]
      // Land a card-sized box centered on the target zone.
      const to = {
        x: target.x + target.w / 2 - dims.w / 2,
        y: target.y + target.h / 2 - dims.h / 2,
        w: dims.w,
        h: dims.h,
      }
      setDealGhosts((cur) => [
        ...cur,
        { id: dealLaunched.current, ...entry, size, from, to },
      ])
    }, DEAL_STEP_MS)

    return () => clearInterval(dealTimer.current)
  }, [dealing, gameState])

  // Every scripted card has visually landed — hold a beat, then hand the
  // table back to plain live-state rendering (a no-op visually: the clamped
  // counts already equal the real ones at this point).
  useEffect(() => {
    if (!dealing || !dealScript.current) return undefined
    if (dealLanded < dealScript.current.length) return undefined
    const timer = setTimeout(endDeal, 250)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- endDeal is stable in effect
  }, [dealing, dealLanded])

  // A snapshot can reshape the rows mid-selection (AFK-forced pickup, a
  // reclaim from another tab). Selection ids are positional within the
  // rendered rows, so prune whatever the new snapshot no longer backs
  // rather than letting a confirm send cards that moved out from under it.
  useEffect(() => {
    if (!gameState) return
    const validIds = new Set([
      ...sortHand(gameState.you.hand).map((spec, i) => `hand-${spec}-${i}`),
      ...gameState.you.face_up.map((spec, i) => `faceup-${spec}-${i}`),
    ])
    setSelection((cur) => {
      const kept = cur.filter((s) => validIds.has(s.id))
      return kept.length === cur.length ? cur : kept
    })
  }, [gameState])

  const secondsLeft = useTurnCountdown(gameState)

  if (!gameState) {
    return (
      <main className="screen game">
        <p className="loading">Connecting to the table…</p>
      </main>
    )
  }

  const you = gameState.you
  const nameById = Object.fromEntries(gameState.players.map((p) => [p.player_id, p.name]))
  const myTurn = gameState.current_player_id === you.player_id
  const currentName = nameById[gameState.current_player_id]
  const seatCount = gameState.players.length
  const myIdx = gameState.players.findIndex((p) => p.player_id === you.player_id)
  // Ring seats are opponents only — your own status lives in the you-area
  // panel, so drawing you on the ring said the same thing twice. Order
  // starts with the player after you; ring slot 0 (bottom-center) stays
  // reserved as your implied anchor, so opponent angles and the direction
  // ring keep the exact same geometry as when your seat was drawn there.
  const opponents = [
    ...gameState.players.slice(myIdx + 1),
    ...gameState.players.slice(0, myIdx),
  ]

  // While dealing, everything renders clamped to how many cards have
  // visually landed per seat and layer. Cheap to recompute per frame — the
  // script is at most 45 entries.
  let dealShown = null
  if (dealing) {
    dealShown = Object.fromEntries(
      gameState.players.map((p) => [p.player_id, { blind: 0, face_up: 0, hand: 0 }])
    )
    dealScript.current?.slice(0, dealLanded).forEach((e) => {
      dealShown[e.pid][e.layer] += 1
    })
  }
  const youShown = dealShown?.[you.player_id]
  const youBlindCount = youShown ? Math.min(you.blind_count, youShown.blind) : you.blind_count
  const youFaceUp = youShown ? you.face_up.slice(0, youShown.face_up) : you.face_up
  // Dealt order while dealing (ghosts land left to right as they fly in),
  // sorted the moment the deal settles.
  const youHand = youShown ? you.hand.slice(0, youShown.hand) : sortHand(you.hand)

  // Once the hand is gone, the face-up row IS the hand: same rows, same size,
  // same controls. Only the id prefix stays layer-specific, so the selection
  // pruning above keeps recognising these cards without knowing they moved.
  const activeLayer = you.active_layer
  const activeCards = activeLayer === 'hand' ? youHand : activeLayer === 'face_up' ? youFaceUp : []
  const activeIdPrefix = activeLayer === 'face_up' ? 'faceup' : 'hand'
  const faceUpPromoted = activeLayer === 'face_up'

  // A picked-up pile can easily put 9+ cards in hand. Rather than let one
  // fan run off the side into a horizontal scroll, split it into stacked
  // rows so the whole hand is visible at once. HAND_ROW_MAX is fixed
  // rather than measured: at 390px the row has ~350px of usable width and
  // a card--md fan steps 36px per card after the first 52px, so 6 fits
  // with room to spare for the arc's tilt. Rows are then evened out
  // (9 renders 5+4, not 6+3) so neither row looks like a leftover.
  const handRows = []
  if (activeCards.length > 0) {
    const rowCount = Math.ceil(activeCards.length / HAND_ROW_MAX)
    const perRow = Math.ceil(activeCards.length / rowCount)
    for (let start = 0; start < activeCards.length; start += perRow) {
      handRows.push(
        activeCards.slice(start, start + perRow).map((spec, k) => ({ spec, i: start + k }))
      )
    }
  }

  // Only an illegal_move names a card. A duplicate rank+suit (two-deck
  // games) marks both copies — they're the same card, both equally refused.
  const rejectedCard = error?.code === 'illegal_move' ? error.card : null

  // Never block a tap on legality — the server is the only judge. We only
  // dim things that are obviously not actionable right now. The tapped
  // element's rect is remembered so that if the server accepts the play,
  // the flight animation can start from the exact card that was tapped.
  const playCard = (spec, el) => {
    pendingTapRef.current = { spec, rect: rectOf(el) }
    sendAction({ action: 'play', card: spec })
  }
  const flipBlind = (index) => sendAction({ action: 'flip', index })
  const pickUpPile = () => sendAction({ action: 'pick_up' })

  // Mirrors the server's validation rather than replacing it: the server
  // rejects empty text too, this just avoids sending a frame that can only
  // be refused. Length is capped by the input's maxLength.
  const sendChat = (text) => {
    const trimmed = text.trim()
    if (!trimmed) return
    sendAction({ action: 'chat', text: trimmed })
  }

  const submitChatDraft = () => {
    sendChat(chatDraft)
    setChatDraft('')
  }

  const openChat = () => {
    setChatOpen(true)
    setUnread(0)
  }

  const selectionRank = selection.length > 0 ? parseCard(selection[0].spec).rank : null
  const selectedIds = new Set(selection.map((s) => s.id))

  // The same-rank rule below is a selection-shape rule, not a legality
  // check: a mixed-rank group isn't a move for the server to arbitrate,
  // it's a shape this UI can't express — same category as `dimmed`, an
  // obviously-not-actionable client-side hint.
  const tapCard = (id, spec, el) => {
    if (!multiSelectMode) {
      playCard(spec, el)
      return
    }
    if (selectedIds.has(id)) {
      setSelection((cur) => cur.filter((s) => s.id !== id))
    } else if (selectionRank == null || parseCard(spec).rank === selectionRank) {
      setSelection((cur) => [...cur, { id, spec, rect: rectOf(el) }])
    }
    // rank mismatch: no-op — the card is rendered dimmed to say why
  }

  const exitMultiSelect = () => {
    setMultiSelectMode(false)
    setSelection([])
  }

  const confirmMultiPlay = () => {
    if (selection.length === 0) return
    // Only the first selected card gets a flight animation: the play
    // event's `card` is documented as the first card of the group, and
    // runMotion animates exactly one ghost. The rest of the group just
    // vanishes from the row when the next snapshot lands — simultaneous
    // multi-card flight is deferred to a later phase.
    pendingTapRef.current = { spec: selection[0].spec, rect: selection[0].rect }
    sendAction({ action: 'play', cards: selection.map((s) => s.spec) })
    // Exit optimistically; a rejection surfaces through the normal error
    // toast and the player re-selects if they want to retry.
    exitMultiSelect()
  }

  return (
    <main className="screen game">
      {status !== 'connected' && (
        <ConnectionBanner status={status} onReclaim={reclaim} />
      )}

      <header className="game-header">
        <span className="game-room">{gameState.room_code}</span>
        <span className="chip">
          {gameState.phase === 'deck' ? `Deck phase · ${gameState.draw_deck_count} left` : 'Hand phase'}
        </span>
        <span className="chip" title={gameState.direction === 1 ? 'Play order: clockwise' : 'Play order: reversed'}>
          {gameState.direction === 1 ? '⟳' : '⟲'}
        </span>
        <button
          type="button"
          className={chatOpen ? 'chip chat-toggle chat-toggle--open' : 'chip chat-toggle'}
          onClick={() => (chatOpen ? setChatOpen(false) : openChat())}
          aria-label={unread > 0 ? `Chat, ${unread} unread` : 'Chat'}
        >
          💬
          {unread > 0 && !chatOpen && <span className="chat-unread">{unread > 9 ? '9+' : unread}</span>}
        </button>
      </header>


      {/* Keys make React remount the banner when whose-turn (not just its
          styling) changes, which retriggers the banner-in entrance. Styling
          shifts on the SAME turn — urgent restyle, waiting threshold — keep
          the mount and glide via the CSS color transitions instead. */}
      {gameState.game_over ? (
        <TurnBanner key="over" className="turn-banner--over" text="Game over" />
      ) : myTurn ? (
        <TurnBanner
          key="you"
          className={
            'turn-banner--you' +
            (secondsLeft != null && secondsLeft <= URGENT_SECONDS ? ' turn-banner--urgent' : '')
          }
          text="Your turn"
        >
          {secondsLeft != null && <span className="turn-countdown">{secondsLeft}s</span>}
        </TurnBanner>
      ) : secondsLeft != null && secondsLeft <= STALL_WARNING_SECONDS ? (
        <TurnBanner
          key={`turn-${gameState.current_player_id}`}
          className="turn-banner--waiting"
          text={`Waiting on ${currentName ?? '…'}`}
        >
          <span className="turn-countdown">{secondsLeft}s</span>
        </TurnBanner>
      ) : (
        <TurnBanner key={`turn-${gameState.current_player_id}`} text={`${currentName ?? '…'}'s turn`} />
      )}

      {gameState.seven_pending && (
        <p className={myTurn ? 'seven-warning seven-warning--you' : 'seven-warning'}>
          7 in effect — next play must be 7 or lower, or a power card
        </p>
      )}

      {/* Minimal follow-up signal (full UI treatment is a later phase):
          without this line the table looks like it's waiting on the wrong
          player, since a pickup or a 2 no longer passes the turn. */}
      {gameState.pending_action && !gameState.game_over && (
        <p className={myTurn ? 'seven-warning seven-warning--you' : 'seven-warning'}>
          {myTurn
            ? gameState.pending_action === 'flip'
              ? 'Bonus flip — flip another blind card!'
              : 'Throw again — play one more card to end your turn'
            : `${currentName ?? 'Someone'} must ${
                gameState.pending_action === 'flip' ? 'flip' : 'throw'
              } again`}
        </p>
      )}

      <section
        className={seatCount <= 3 ? 'round-table round-table--few' : 'round-table'}
        aria-label="Table"
      >
        <DirectionRing
          count={seatCount}
          direction={gameState.direction}
          flash={powerFx?.rank === 'J'}
        />

        {/* Keyed on the fx id so a second J while the first is still fading
            restarts the glyph instead of leaving it mid-flight. */}
        {powerFx?.rank === 'J' && (
          <div className="reverse-flash" key={powerFx.id} aria-hidden="true">
            {gameState.direction === 1 ? '⟳' : '⟲'}
          </div>
        )}

        {opponents.map((player, j) => (
          <TableSeat
            key={player.player_id}
            player={player}
            isCurrent={player.player_id === gameState.current_player_id}
            flashForced={forcedFlash?.playerId === player.player_id}
            style={seatPos(j + 1, seatCount)}
            shown={dealShown?.[player.player_id]}
            seatRef={(el) => (seatRefs.current[player.player_id] = el)}
          />
        ))}

        <div className="table-hub">
          <div className="draw-deck">
            <div ref={deckRef}>
              {gameState.draw_deck_count > 0 ? (
                <Card hidden size="sm" label={`Draw deck, ${gameState.draw_deck_count} cards`} />
              ) : (
                <div className="card card--sm card--slot" aria-hidden="true" />
              )}
            </div>
            <span className="zone-caption">deck · {gameState.draw_deck_count}</span>
          </div>

          <DiscardPile
            pile={gameState.discard_pile}
            stackRef={discardRef}
            burning={burn != null}
            fx={powerFx?.rank === 'J' ? null : powerFx}
            ruleBadge={ruleBadge}
          />
        </div>
      </section>

      <p
        className={lastEvent?.forced ? 'event-line event-line--forced' : 'event-line'}
        aria-live="polite"
      >
        {lastEvent ? describeEvent(lastEvent, nameById) : ' '}
      </p>

      <section
        ref={youAreaRef}
        className={[
          'you-area',
          myTurn && !gameState.game_over ? 'you-area--turn' : '',
          forcedFlash?.playerId === you.player_id ? 'you-area--forced' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        aria-label="Your cards"
      >
        <div className="you-row you-row--blind">
          <span
            className={
              you.active_layer === 'blind' && !you.finish_position
                ? 'row-caption row-caption--active'
                : 'row-caption'
            }
          >
            blind{you.active_layer === 'blind' && !you.finish_position ? ' — tap to flip!' : ''}
          </span>
          <div className="row-cards" ref={blindRowRef}>
            {Array.from({ length: youBlindCount }, (_, i) => (
              <Card
                key={i}
                hidden
                patternSeed={`${you.player_id}:${i}`}
                size="sm"
                dimmed={you.active_layer !== 'blind' || !myTurn}
                onClick={() => flipBlind(i)}
                label={`Blind card ${i + 1}`}
              />
            ))}
            {youBlindCount === 0 && !dealing && <span className="row-empty">cleared</span>}
          </div>
        </div>

        <div className="you-row you-row--faceup">
          <span className="row-caption">face-up</span>
          {/* Promoted: these cards now render full-size in the hand section
              below, so the preview row would be showing them twice. */}
          <div className="row-cards" ref={faceUpRowRef}>
            {faceUpPromoted && <span className="row-empty">cleared</span>}
            {!faceUpPromoted && youFaceUp.map((spec, i) => {
              const id = `faceup-${spec}-${i}`
              const rankMismatch =
                multiSelectMode && selectionRank != null && parseCard(spec).rank !== selectionRank
              return (
                <Card
                  key={`${spec}-${i}`}
                  spec={spec}
                  size="sm"
                  dimmed={you.active_layer !== 'face_up' || !myTurn || rankMismatch}
                  selected={selectedIds.has(id)}
                  rejected={spec === rejectedCard}
                  onClick={(e) => tapCard(id, spec, e.currentTarget)}
                />
              )
            })}
            {!faceUpPromoted && youFaceUp.length === 0 && !dealing && (
              <span className="row-empty">cleared</span>
            )}
          </div>
        </div>

        <div className="you-row you-row--hand">
          <div className="hand-header">
            {/* Always "hand", whichever layer is feeding it — during face-up
                play these cards ARE the player's hand. */}
            <span className="row-caption">hand · {activeCards.length}</span>
            <div className="hand-actions">
              {multiSelectMode ? (
                <>
                  <button
                    className="button button--tiny button--quiet"
                    type="button"
                    onClick={exitMultiSelect}
                  >
                    Cancel
                  </button>
                  <button
                    className="button button--tiny button--gold"
                    type="button"
                    disabled={selection.length === 0}
                    onClick={confirmMultiPlay}
                  >
                    Play {selection.length}
                  </button>
                </>
              ) : (
                <button
                  className="button button--tiny button--quiet"
                  type="button"
                  disabled={gameState.game_over}
                  onClick={() => setMultiSelectMode(true)}
                >
                  Throw multiples
                </button>
              )}
              <button
                className="button button--pickup"
                type="button"
                // A pending follow-up bars pickup server-side; dim the button
                // so the rule is visible before the error toast would be.
                disabled={gameState.game_over || (myTurn && gameState.pending_action != null)}
                onClick={pickUpPile}
              >
                Pick up pile
              </button>
            </div>
          </div>
          <div className="row-cards row-cards--hand" ref={handRowRef}>
            {handRows.map((row, r) => (
              <div className="hand-fan" key={`fan-${r}`}>
                {row.map(({ spec, i }, j) => {
                  // `i` is the card's index in the whole hand, not in this
                  // row — identity (and therefore selection) must not shift
                  // when a card lands in a different row.
                  const id = `${activeIdPrefix}-${spec}-${i}`
                  const rankMismatch =
                    multiSelectMode &&
                    selectionRank != null &&
                    parseCard(spec).rank !== selectionRank
                  const isSelected = selectedIds.has(id)
                  const isRejected = spec === rejectedCard
                  // Fan geometry, reset per row: each row is its own small
                  // self-contained arc centred on itself, rather than one
                  // long arc sliced in half. Rotation is linear across the
                  // row (edges capped at ±15°) with a shallow lift — edge
                  // cards drop with their tilt. Wrappers carry these so the
                  // Card's own transform states (selected lift, rejected
                  // shake, press) compose instead of clash.
                  const mid = (row.length - 1) / 2
                  const rot = (j - mid) * Math.min(6, 30 / Math.max(row.length - 1, 1))
                  return (
                    <span
                      key={`${spec}-${i}`}
                      className={
                        isSelected || isRejected ? 'fan-card fan-card--raised' : 'fan-card'
                      }
                      // Left-to-right stacking within the row: each card
                      // overlaps the one before it, so a card's exposed
                      // left sliver is always its own tap target.
                      style={{
                        '--fan-rot': `${rot.toFixed(1)}deg`,
                        '--fan-lift': `${Math.abs(rot * 0.6).toFixed(1)}px`,
                        zIndex: j + 1,
                      }}
                    >
                      <Card
                        spec={spec}
                        size="md"
                        dimmed={!myTurn || rankMismatch}
                        selected={isSelected}
                        rejected={isRejected}
                        onClick={(e) => tapCard(id, spec, e.currentTarget)}
                      />
                    </span>
                  )
                })}
              </div>
            ))}
            {activeCards.length === 0 && !dealing && <span className="row-empty">empty</span>}
          </div>
        </div>
      </section>

      {flights.map((flight) => (
        <FlightCard
          key={flight.id}
          flight={flight}
          onDone={() => setFlights((cur) => cur.filter((f) => f.id !== flight.id))}
        />
      ))}

      {dealGhosts.map((ghost) => (
        <DealFlight
          key={ghost.id}
          ghost={ghost}
          onLand={() => setDealLanded((n) => n + 1)}
          onDone={() => setDealGhosts((cur) => cur.filter((g) => g.id !== ghost.id))}
        />
      ))}

      {burn && (
        <>
          <div
            className="burn-ghost"
            key={`ghost-${burn.id}`}
            style={{ left: burn.rect.x, top: burn.rect.y, width: burn.rect.w, height: burn.rect.h }}
            aria-hidden="true"
          >
            <Card spec={burn.spec} size="lg" />
          </div>
          {/* Keyed on the burn id: a fresh mount per nuke is what guarantees
              the previous lottie instance was destroyed before this one
              loads (see BurnFire's cleanup). */}
          <BurnFire key={`fire-${burn.id}`} rect={burn.rect} />
        </>
      )}

      {/* Centred rather than drawn at the flipper's seat: the seat markers
          are far too small on a phone to read a card off. Keyed on the
          sequence number so a chained flip remounts (and replays) instead of
          swapping the face inside a card that's already sitting still. */}
      {blindReveal && (
        <div className="blind-reveal" key={blindReveal.id} aria-hidden="true">
          <div className="blind-reveal-card">
            <Card spec={blindReveal.card} size="lg" />
          </div>
          <span className="blind-reveal-caption">
            {nameById[blindReveal.playerId] ?? 'Someone'} flips blind
          </span>
        </div>
      )}

      {/* Anchored over each speaker, centred on the seat/you-area rect that
          was measured when the message landed. pointer-events: none in CSS
          — a bubble must never swallow a tap on the card underneath it. */}
      {bubbles.map((bubble) => (
        <div
          key={bubble.id}
          className={[
            'chat-bubble',
            bubble.below ? 'chat-bubble--below' : '',
            isReaction(bubble.text) ? 'chat-bubble--reaction' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          style={{ left: bubble.x, top: bubble.y }}
          aria-hidden="true"
        >
          {bubble.text}
        </div>
      ))}

      {chatOpen && (
        <ChatDrawer
          log={chatLog}
          nameById={nameById}
          youId={you.player_id}
          draft={chatDraft}
          listRef={chatListRef}
          onDraftChange={setChatDraft}
          onSend={submitChatDraft}
          onQuickSend={sendChat}
          onClose={() => setChatOpen(false)}
        />
      )}

      {error && (
        <div className={`toast toast--${error.code}`} role="alert">{error.message}</div>
      )}

      {gameState.game_over && (
        <GameOverOverlay
          finishOrder={gameState.finish_order}
          nameById={nameById}
          youId={you.player_id}
          onLeave={onLeave}
        />
      )}
    </main>
  )
}

function TurnBanner({ className = '', text, children }) {
  return (
    <div className={`turn-banner ${className}`}>
      {text}
      {children}
    </div>
  )
}

// Mirrors the server's AFK clock locally. Every state frame carries
// turn_ends_in measured at send time (docs/WS_PROTOCOL.md), so this never
// free-runs from a guess: a reconnect snapshot mid-turn resumes at the
// server's real remaining time instead of restarting at 60.
function useTurnCountdown(gameState) {
  const [secondsLeft, setSecondsLeft] = useState(null)

  useEffect(() => {
    if (!gameState || gameState.game_over || gameState.turn_ends_in == null) {
      setSecondsLeft(null)
      return
    }
    const deadline = Date.now() + gameState.turn_ends_in * 1000
    const tick = () => setSecondsLeft(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)))
    tick()
    // 500ms, not 1s: a 1s interval visibly skips numbers when it beats
    // against the deadline fraction.
    const timer = setInterval(tick, 500)
    return () => clearInterval(timer)
  }, [gameState])

  return secondsLeft
}

function ConnectionBanner({ status, onReclaim }) {
  if (status === 'superseded') {
    return (
      <div className="conn-banner conn-banner--superseded">
        Opened somewhere else.
        <button className="button button--tiny" type="button" onClick={onReclaim}>Resume here</button>
      </div>
    )
  }
  return (
    <div className="conn-banner">
      {status === 'connecting' ? 'Connecting…' : 'Connection lost — reconnecting…'}
    </div>
  )
}

// One opponent seat on the circular table: a light marker on the felt —
// avatar, name, compact blind+face-up stack. Hands never appear here as
// cards, only as a count. Your own seat is never drawn; the you-area below
// is your seat. `shown` (while the deal animation runs) clamps each layer
// to how many cards have visually landed.
function TableSeat({ player, isCurrent, flashForced, style, shown, seatRef }) {
  const finished = player.finish_position != null
  const classes = ['seat']
  if (isCurrent) classes.push('seat--current')
  if (flashForced) classes.push('seat--forced')

  const blindCount = shown ? Math.min(player.blind_count, shown.blind) : player.blind_count
  const faceUp = shown ? player.face_up.slice(0, shown.face_up) : player.face_up
  const handCount = shown ? Math.min(player.hand_count, shown.hand) : player.hand_count
  const columns = Math.max(blindCount, faceUp.length)

  return (
    <div ref={seatRef} className={classes.join(' ')} style={style}>
      <span className="seat-id">
        <span className="avatar avatar--seat" aria-hidden="true">
          {player.name.charAt(0).toUpperCase()}
        </span>
        <span className="seat-name">{player.name}</span>
      </span>
      {finished ? (
        <span className="seat-finished">{ordinal(player.finish_position)}</span>
      ) : (
        <>
          <span className="seat-stack" aria-hidden="true">
            {Array.from({ length: columns }, (_, i) => (
              <span key={i} className="stack-col">
                {i < blindCount && (
                  <span className="stack-blind">
                    <Card hidden patternSeed={`${player.player_id}:${i}`} size="xs" />
                  </span>
                )}
                {i < faceUp.length && (
                  <span className="stack-faceup">
                    <Card spec={faceUp[i]} size="xs" />
                  </span>
                )}
              </span>
            ))}
          </span>
          <span className="seat-hand" title="cards in hand">✋{handCount}</span>
        </>
      )}
    </div>
  )
}

// Chevrons at the midpoints between seats, pointing along the current flow
// of play and pulsing in flow order — a J's reverse visibly flips the whole
// ring, not just the header icon. Keyed by direction so the marching
// animation restarts cleanly on a flip.
function DirectionRing({ count, direction, flash }) {
  const chevrons = Array.from({ length: count }, (_, k) => {
    const a = seatAngle(k + 0.5, count)
    // Tangent to the ellipse: +90° points clockwise (the direction === 1
    // flow, matching seat order on screen), -90° counterclockwise.
    const deg = (a * 180) / Math.PI + (direction === 1 ? 90 : -90)
    const flowIndex = direction === 1 ? k : count - 1 - k
    return (
      <span
        key={`${direction}-${k}`}
        className="ring-chevron"
        style={{
          left: `${50 + SEAT_RX * Math.cos(a)}%`,
          top: `${50 + SEAT_RY * Math.sin(a)}%`,
          // The surge keyframe has to rebuild the whole transform, so the
          // chevron's own angle lives in a custom property both can read.
          '--chevron-rot': `${deg}deg`,
          transform: `translate(-50%, -50%) rotate(${deg}deg)`,
          animationDelay: `${((flowIndex / count) * 1.8).toFixed(2)}s`,
        }}
      >
        ❯
      </span>
    )
  })
  return (
    <div className={flash ? 'direction-ring direction-ring--flash' : 'direction-ring'} aria-hidden="true">
      {chevrons}
    </div>
  )
}

// The 10-nuke's fire, played once over the discard pile. lottie-web's
// imperative API rather than a React wrapper, to match how every other
// transient effect on this screen is managed (a ref, an effect, explicit
// teardown). Mounted keyed per burn, so the effect body runs exactly once
// per nuke and destroy() always pairs with its own loadAnimation().
function BurnFire({ rect }) {
  const hostRef = useRef(null)

  useEffect(() => {
    // display: none would still leave the instance rendering frames every
    // tick, so reduced-motion has to be answered here, not only in CSS.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined
    const anim = lottie.loadAnimation({
      container: hostRef.current,
      animationData: fireAnimation,
      renderer: 'svg',
      loop: false,
      autoplay: true,
    })
    return () => anim.destroy()
  }, [])

  // Square box, centred on the card horizontally and hung so the flame's
  // root lands just inside the card's bottom edge.
  const size = rect.h * FIRE_SCALE
  return (
    <div
      ref={hostRef}
      className="burn-fire"
      style={{
        left: rect.x + rect.w / 2 - size / 2,
        top: rect.y + rect.h - size * FIRE_BASE,
        width: size,
        height: size,
      }}
      aria-hidden="true"
    />
  )
}

// One dealt card flying from the center deck to its seat (or to your hand
// row). Same anchored-at-destination transform trick as FlightCard, but
// with a separate onLand beat: the moment the ghost visually arrives, the
// real card pops in underneath and the ghost fades over it.
function DealFlight({ ghost, onLand, onDone }) {
  const [arrived, setArrived] = useState(false)

  useEffect(() => {
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setArrived(true)))
    const landTimer = setTimeout(onLand, DEAL_LAND_MS)
    const doneTimer = setTimeout(onDone, DEAL_CLEANUP_MS)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(landTimer)
      clearTimeout(doneTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per ghost
  }, [])

  const { from, to } = ghost
  const dx = from.x + from.w / 2 - (to.x + to.w / 2)
  const dy = from.y + from.h / 2 - (to.y + to.h / 2)
  const startScale = Math.max(from.h / to.h, 0.2)

  return (
    <div
      className="deal-flight"
      style={{
        left: to.x,
        top: to.y,
        width: to.w,
        height: to.h,
        transform: arrived
          ? 'translate(0px, 0px) scale(1)'
          : `translate(${dx}px, ${dy}px) scale(${startScale})`,
        opacity: arrived ? 0 : 1,
      }}
      aria-hidden="true"
    >
      {ghost.layer === 'blind' ? (
        <Card hidden patternSeed={ghost.seed} size={ghost.size} />
      ) : ghost.spec ? (
        <Card spec={ghost.spec} size={ghost.size} />
      ) : (
        <Card hidden size={ghost.size} />
      )}
    </div>
  )
}

function DiscardPile({ pile, stackRef, burning, fx, ruleBadge }) {
  const topCard = pile.length > 0 ? pile[pile.length - 1] : null

  // Consecutive power cards on top of the pile stay visible as a fanned
  // stack (power cards can stack on each other, and the table should see
  // the run — e.g. a 7 hiding under a J still constrains reads).
  const powerStack = []
  for (let i = pile.length - 1; i >= 0 && parseCard(pile[i]).power; i--) {
    powerStack.unshift(pile[i])
  }
  const fanned = powerStack.length > 1 ? powerStack.slice(0, -1).slice(-3) : []

  return (
    <div className="discard">
      {/* Keyed so a 7 played while the previous badge is still fading
          restarts it rather than inheriting the old element's timeline. */}
      {ruleBadge && (
        <span className="pile-rule-badge" key={ruleBadge.id}>
          {ruleBadge.text}
        </span>
      )}
      <div className={burning ? 'discard-stack discard-stack--burning' : 'discard-stack'} ref={stackRef}>
        {/* 2's pulse / 7's ripple. A real keyed element rather than a class
            on the stack, so a follow-up throw of the same rank remounts and
            replays it instead of silently reusing a running animation — and
            so the stack (and the rect the flight animation measures off it)
            never remounts. */}
        {fx && (
          <span className={`pile-fx pile-fx--${fx.rank === '2' ? 'reset' : 'seven'}`} key={fx.id} />
        )}
        {fanned.map((spec, i) => (
          <div key={`${spec}-${i}`} className="discard-under" style={{ transform: `translateX(${(i - fanned.length) * 14}px) rotate(${(i - fanned.length) * 4}deg)` }}>
            <Card spec={spec} size="sm" />
          </div>
        ))}
        {topCard ? (
          // Keyed per state change so a new top card re-runs the 150ms
          // arrive animation (the flight ghost lands right on top of it).
          <div key={`${topCard}-${pile.length}`} className="discard-top">
            <Card spec={topCard} size="lg" />
          </div>
        ) : (
          <div className="card card--lg card--slot">
            <span className="slot-text">any card</span>
          </div>
        )}
      </div>
      <span className="zone-caption">pile · {pile.length}</span>
    </div>
  )
}

// A played card's ghost, flying from where it was tapped (or from the
// player's seat, for opponents) to the discard pile. Anchored at the
// destination and transformed back to the source, so the browser only ever
// animates transform/opacity. Purely decorative: the real state swap has
// already happened underneath, and pointer-events never pass through it.
function FlightCard({ flight, onDone }) {
  const [arrived, setArrived] = useState(false)

  useEffect(() => {
    // Double rAF: the first frame must paint at the source position before
    // the transition target is set, or the browser skips the animation.
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setArrived(true)))
    const timer = setTimeout(onDone, FLIGHT_CLEANUP_MS)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per ghost
  }, [])

  const { from, to, spec } = flight
  const dx = from.x + from.w / 2 - (to.x + to.w / 2)
  const dy = from.y + from.h / 2 - (to.y + to.h / 2)
  const startScale = Math.max(from.h / to.h, 0.2)

  return (
    <div
      className="flight"
      style={{
        left: to.x,
        top: to.y,
        width: to.w,
        height: to.h,
        transform: arrived
          ? 'translate(0px, 0px) scale(1)'
          : `translate(${dx}px, ${dy}px) scale(${startScale})`,
        opacity: arrived ? 0 : 1,
      }}
      aria-hidden="true"
    >
      <Card spec={spec} size="lg" />
    </div>
  )
}

// Bottom sheet, mounted only while open so it takes zero layout space (and
// costs no taps) the rest of the time. Deliberately not an .overlay: the
// table stays visible and playable behind it — you can watch a turn resolve
// while typing.
function ChatDrawer({
  log,
  nameById,
  youId,
  draft,
  listRef,
  onDraftChange,
  onSend,
  onQuickSend,
  onClose,
}) {
  return (
    <div className="chat-drawer">
      <div className="chat-drawer-head">
        <span className="row-caption">chat</span>
        <button className="button button--tiny button--quiet" type="button" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="chat-log" ref={listRef}>
        {log.length === 0 && <span className="row-empty">no messages yet</span>}
        {log.map((entry) => (
          <p
            key={entry.id}
            className={entry.player_id === youId ? 'chat-line chat-line--you' : 'chat-line'}
          >
            <span className="chat-author">{nameById[entry.player_id] ?? 'Someone'}</span>
            {/* Plain text child, never dangerouslySetInnerHTML — React's
                default escaping is the whole defence here. */}
            <span className={isReaction(entry.text) ? 'chat-text chat-text--reaction' : 'chat-text'}>
              {entry.text}
            </span>
          </p>
        ))}
      </div>

      {/* One tap = one message. The glyph goes over the wire as ordinary
          chat text; only the rendering treats it as a reaction. */}
      <div className="chat-quick">
        {QUICK_EMOJI.map((glyph) => (
          <button
            key={glyph}
            className="chat-quick-btn"
            type="button"
            onClick={() => onQuickSend(glyph)}
            aria-label={`Send ${glyph}`}
          >
            {glyph}
          </button>
        ))}
      </div>

      <form
        className="chat-compose"
        onSubmit={(e) => {
          e.preventDefault()
          onSend()
        }}
      >
        <input
          className="chat-input"
          type="text"
          value={draft}
          maxLength={CHAT_MAX_LENGTH}
          placeholder="Say something…"
          onChange={(e) => onDraftChange(e.target.value)}
          aria-label="Chat message"
        />
        <button
          className="button button--tiny button--gold"
          type="submit"
          disabled={draft.trim().length === 0}
        >
          Send
        </button>
      </form>
    </div>
  )
}

function GameOverOverlay({ finishOrder, nameById, youId, onLeave }) {
  return (
    <div className="overlay">
      <div className="overlay-panel">
        <h2 className="overlay-title">Final standings</h2>
        <ol className="standings">
          {finishOrder.map((playerId, i) => (
            <li
              key={playerId}
              className={
                'standing' +
                (playerId === youId ? ' standing--you' : '') +
                (i === finishOrder.length - 1 ? ' standing--last' : '')
              }
            >
              <span className="standing-place">{ordinal(i + 1)}</span>
              <span className="standing-name">
                {nameById[playerId] ?? '???'}
                {playerId === youId && ' (you)'}
              </span>
            </li>
          ))}
        </ol>
        <button className="button button--primary" type="button" onClick={onLeave}>
          Back to start
        </button>
      </div>
    </div>
  )
}

function describeEvent(event, nameById) {
  const name = nameById[event.player_id] ?? 'Someone'
  if (event.kind === 'play') {
    let text = `${name} played ${prettyCard(event.card)}`
    if (event.pile_burned) text += ' — pile burned!'
    if (event.direction_reversed) text += ' — direction reversed'
    if (event.must_throw_again) text += ' — throws again!'
    if (event.player_finished) text += ` · ${name} is out!`
    return text
  }
  if (event.kind === 'pickup') {
    const how = event.forced ? 'timed out — picked up the pile' : 'picked up the pile'
    let text = `${name} ${how} (${event.count} ${event.count === 1 ? 'card' : 'cards'})`
    if (event.must_throw_again) text += ' — must throw a card'
    return text
  }
  if (event.kind === 'skip') {
    return `${name} timed out — turn skipped`
  }
  if (event.kind === 'flip') {
    let text = event.forced
      ? `${name} timed out — flipped ${prettyCard(event.card)}`
      : `${name} flipped ${prettyCard(event.card)}`
    if (event.played) {
      text += ' — it plays!'
      if (event.pile_burned) text += ' Pile burned!'
      if (event.direction_reversed) text += ' Direction reversed.'
      if (event.must_flip_again) text += ' Flips again!'
      if (event.player_finished) text += ` ${name} is out!`
    } else if (event.picked_up) {
      text += ' — no good, pile picked up'
      if (event.must_throw_again) text += ' — must throw a card'
    }
    return text
  }
  return null
}

function ordinal(n) {
  const suffix =
    n % 100 >= 11 && n % 100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'
  return `${n}${suffix}`
}
