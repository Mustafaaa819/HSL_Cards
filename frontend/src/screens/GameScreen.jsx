import { useEffect, useRef, useState } from 'react'
import Card from '../components/Card.jsx'
import { useGameSocket } from '../hooks/useGameSocket.js'
import { parseCard, prettyCard, sortHand } from '../cards.js'

// Once a turn has been stalled this long, everyone gets told who the table
// is waiting on — otherwise the eventual forced pickup/flip/skip looks like
// a glitch to the other players.
const STALL_WARNING_SECONDS = 30
const URGENT_SECONDS = 10

// Flight/burn/flash durations live in App.css; these only bound how long the
// transient DOM for each effect sticks around. Generous on purpose — removal
// a beat late is invisible, removal a beat early truncates the animation.
const FLIGHT_CLEANUP_MS = 450
const BURN_CLEANUP_MS = 750
const FORCED_FLASH_MS = 900

const rectOf = (el) => {
  if (!el) return null
  const { x, y, width, height } = el.getBoundingClientRect()
  return { x, y, w: width, h: height }
}

export default function GameScreen({ session, onLeave, onFatalClose }) {
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
  const discardRef = useRef(null)
  const blindRowRef = useRef(null)
  const youAreaRef = useRef(null)
  const seatRefs = useRef({})
  const pendingTapRef = useRef(null) // { spec, rect } of the card just tapped
  const burnTimer = useRef(null)
  const flashTimer = useRef(null)

  const runMotion = (event, state) => {
    const to = rectOf(discardRef.current)
    if (!to) return
    const myId = state.you.player_id

    if ((event.kind === 'play' || event.kind === 'flip') && event.pile_burned) {
      // A nuke gets its own bigger beat instead of the normal flight: the 10
      // pops onto the pile and torches it. Timestamp key so back-to-back
      // burns (rare, but legal) each restart the animation.
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
    }
    pendingTapRef.current = null

    if (event.forced) {
      setForcedFlash({ playerId: event.player_id })
      clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setForcedFlash(null), FORCED_FLASH_MS)
    }
  }

  const { gameState, status, sendAction, reclaim } = useGameSocket(session.roomCode, session.token, {
    onServerError: (payload) => {
      clearTimeout(toastTimer.current)
      setError(payload)
      toastTimer.current = setTimeout(() => setError(null), 4000)
    },
    onEvent: (event, state) => {
      setLastEvent(event)
      // The table moved, so any complaint about the old state is stale —
      // drop it rather than leave a card marked against a pile it no
      // longer refers to.
      clearTimeout(toastTimer.current)
      setError(null)
      runMotion(event, state)
    },
    onFatalClose,
  })

  useEffect(
    () => () => {
      clearTimeout(toastTimer.current)
      clearTimeout(burnTimer.current)
      clearTimeout(flashTimer.current)
    },
    []
  )

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
  const opponents = gameState.players.filter((p) => p.player_id !== you.player_id)

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
      </header>

      <section className="opponents" aria-label="Opponents">
        {opponents.map((opponent, i) => (
          <OpponentSeat
            key={opponent.player_id}
            player={opponent}
            isCurrent={opponent.player_id === gameState.current_player_id}
            flashForced={forcedFlash?.playerId === opponent.player_id}
            arcOffset={Math.abs(i - (opponents.length - 1) / 2) * 7}
            seatRef={(el) => (seatRefs.current[opponent.player_id] = el)}
          />
        ))}
      </section>

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

      <section className="table-center">
        <div className="draw-deck">
          {gameState.draw_deck_count > 0 ? (
            <Card hidden size="sm" label={`Draw deck, ${gameState.draw_deck_count} cards`} />
          ) : (
            <div className="card card--sm card--slot" aria-hidden="true" />
          )}
          <span className="zone-caption">deck · {gameState.draw_deck_count}</span>
        </div>

        <DiscardPile pile={gameState.discard_pile} stackRef={discardRef} burning={burn != null} />
      </section>

      <p
        className={lastEvent?.forced ? 'event-line event-line--forced' : 'event-line'}
        aria-live="polite"
      >
        {lastEvent ? describeEvent(lastEvent, nameById) : ' '}
      </p>

      <section
        ref={youAreaRef}
        className={
          forcedFlash?.playerId === you.player_id ? 'you-area you-area--forced' : 'you-area'
        }
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
            {Array.from({ length: you.blind_count }, (_, i) => (
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
            {you.blind_count === 0 && <span className="row-empty">cleared</span>}
          </div>
        </div>

        <div className="you-row you-row--faceup">
          <span
            className={
              you.active_layer === 'face_up' ? 'row-caption row-caption--active' : 'row-caption'
            }
          >
            face-up{you.active_layer === 'face_up' ? ' — in play' : ''}
          </span>
          <div className="row-cards">
            {you.face_up.map((spec, i) => {
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
            {you.face_up.length === 0 && <span className="row-empty">cleared</span>}
          </div>
        </div>

        <div className="you-row you-row--hand">
          <div className="hand-header">
            <span className="row-caption">hand · {you.hand.length}</span>
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
          <div className="row-cards row-cards--hand">
            {sortHand(you.hand).map((spec, i) => {
              const id = `hand-${spec}-${i}`
              const rankMismatch =
                multiSelectMode && selectionRank != null && parseCard(spec).rank !== selectionRank
              return (
                <Card
                  key={`${spec}-${i}`}
                  spec={spec}
                  size="md"
                  dimmed={you.active_layer !== 'hand' || !myTurn || rankMismatch}
                  selected={selectedIds.has(id)}
                  rejected={spec === rejectedCard}
                  onClick={(e) => tapCard(id, spec, e.currentTarget)}
                />
              )
            })}
            {you.hand.length === 0 && <span className="row-empty">empty</span>}
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

      {burn && (
        <div
          className="burn-ghost"
          style={{ left: burn.rect.x, top: burn.rect.y, width: burn.rect.w, height: burn.rect.h }}
          aria-hidden="true"
        >
          <Card spec={burn.spec} size="lg" />
        </div>
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

function OpponentSeat({ player, isCurrent, flashForced, arcOffset, seatRef }) {
  const finished = player.finish_position != null
  const classes = ['opponent']
  if (isCurrent) classes.push('opponent--current')
  if (flashForced) classes.push('opponent--forced')
  return (
    <div
      ref={seatRef}
      className={classes.join(' ')}
      style={{ transform: `translateY(${arcOffset}px)` }}
    >
      <span className="avatar" aria-hidden="true">{player.name.charAt(0).toUpperCase()}</span>
      <span className="opponent-name">{player.name}</span>
      {finished ? (
        <span className="opponent-finished">{ordinal(player.finish_position)}</span>
      ) : (
        <>
          <span className="opponent-counts">
            <span title="cards in hand">✋{player.hand_count}</span>
            <span title="blind cards">🂠{player.blind_count}</span>
          </span>
          <span className="opponent-faceup">
            {player.face_up.map((spec, i) => (
              <Card key={`${spec}-${i}`} spec={spec} size="xs" />
            ))}
          </span>
        </>
      )}
    </div>
  )
}

function DiscardPile({ pile, stackRef, burning }) {
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
      <div className={burning ? 'discard-stack discard-stack--burning' : 'discard-stack'} ref={stackRef}>
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
