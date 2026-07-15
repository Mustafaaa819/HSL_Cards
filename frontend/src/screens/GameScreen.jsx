import { useEffect, useRef, useState } from 'react'
import Card from '../components/Card.jsx'
import { useGameSocket } from '../hooks/useGameSocket.js'
import { parseCard, prettyCard, sortHand } from '../cards.js'

export default function GameScreen({ session, onLeave, onFatalClose }) {
  const [toast, setToast] = useState(null)
  const [lastEvent, setLastEvent] = useState(null)
  const toastTimer = useRef(null)

  const { gameState, status, sendAction, reclaim } = useGameSocket(session.roomCode, session.token, {
    onServerError: (message) => {
      clearTimeout(toastTimer.current)
      setToast(message)
      toastTimer.current = setTimeout(() => setToast(null), 4000)
    },
    onEvent: (event) => setLastEvent(event),
    onFatalClose,
  })

  useEffect(() => () => clearTimeout(toastTimer.current), [])

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

  // Never block a tap on legality — the server is the only judge. We only
  // dim things that are obviously not actionable right now.
  const playCard = (spec) => sendAction({ action: 'play', card: spec })
  const flipBlind = (index) => sendAction({ action: 'flip', index })
  const pickUpPile = () => sendAction({ action: 'pick_up' })

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
            arcOffset={Math.abs(i - (opponents.length - 1) / 2) * 7}
          />
        ))}
      </section>

      {gameState.game_over ? (
        <TurnBanner className="turn-banner--over" text="Game over" />
      ) : myTurn ? (
        <TurnBanner className="turn-banner--you" text="Your turn" />
      ) : (
        <TurnBanner text={`${currentName ?? '…'}'s turn`} />
      )}

      {gameState.seven_pending && (
        <p className={myTurn ? 'seven-warning seven-warning--you' : 'seven-warning'}>
          7 in effect — next play must be 7 or lower, or a power card
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

        <DiscardPile pile={gameState.discard_pile} />
      </section>

      <p className="event-line" aria-live="polite">
        {lastEvent ? describeEvent(lastEvent, nameById) : ' '}
      </p>

      <section className="you-area" aria-label="Your cards">
        <div className="you-row you-row--blind">
          <span className="row-caption">
            blind{you.active_layer === 'blind' && !you.finish_position ? ' — tap to flip!' : ''}
          </span>
          <div className="row-cards">
            {Array.from({ length: you.blind_count }, (_, i) => (
              <Card
                key={i}
                hidden
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
          <span className="row-caption">face-up</span>
          <div className="row-cards">
            {you.face_up.map((spec, i) => (
              <Card
                key={`${spec}-${i}`}
                spec={spec}
                size="sm"
                dimmed={you.active_layer !== 'face_up' || !myTurn}
                onClick={() => playCard(spec)}
              />
            ))}
            {you.face_up.length === 0 && <span className="row-empty">cleared</span>}
          </div>
        </div>

        <div className="you-row you-row--hand">
          <div className="hand-header">
            <span className="row-caption">hand · {you.hand.length}</span>
            <button
              className="button button--pickup"
              type="button"
              disabled={gameState.game_over}
              onClick={pickUpPile}
            >
              Pick up pile
            </button>
          </div>
          <div className="row-cards row-cards--hand">
            {sortHand(you.hand).map((spec, i) => (
              <Card
                key={`${spec}-${i}`}
                spec={spec}
                size="md"
                dimmed={you.active_layer !== 'hand' || !myTurn}
                onClick={() => playCard(spec)}
              />
            ))}
            {you.hand.length === 0 && <span className="row-empty">empty</span>}
          </div>
        </div>
      </section>

      {toast && (
        <div className="toast" role="alert">{toast}</div>
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

function TurnBanner({ className = '', text }) {
  return <div className={`turn-banner ${className}`}>{text}</div>
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

function OpponentSeat({ player, isCurrent, arcOffset }) {
  const finished = player.finish_position != null
  return (
    <div
      className={isCurrent ? 'opponent opponent--current' : 'opponent'}
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

function DiscardPile({ pile }) {
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
      <div className="discard-stack">
        {fanned.map((spec, i) => (
          <div key={`${spec}-${i}`} className="discard-under" style={{ transform: `translateX(${(i - fanned.length) * 14}px) rotate(${(i - fanned.length) * 4}deg)` }}>
            <Card spec={spec} size="sm" />
          </div>
        ))}
        {topCard ? (
          <Card spec={topCard} size="lg" />
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
    if (event.player_finished) text += ` · ${name} is out!`
    return text
  }
  if (event.kind === 'pickup') {
    return `${name} picked up the pile (${event.count} cards)`
  }
  if (event.kind === 'flip') {
    let text = `${name} flipped ${prettyCard(event.card)}`
    if (event.played) {
      text += ' — it plays!'
      if (event.pile_burned) text += ' Pile burned!'
      if (event.direction_reversed) text += ' Direction reversed.'
      if (event.player_finished) text += ` ${name} is out!`
    } else if (event.picked_up) {
      text += ' — no good, pile picked up'
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
