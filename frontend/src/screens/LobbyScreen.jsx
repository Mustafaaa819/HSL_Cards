import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const POLL_INTERVAL_MS = 2000

// Lobby is deliberately REST + 2s polling, not WebSocket — a friend group
// staring at a lobby for a few seconds doesn't need realtime (per Phase 4 spec).
export default function LobbyScreen({ session, onStarted, onLeft }) {
  const [room, setRoom] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const startedRef = useRef(false)

  const handleStarted = useCallback(() => {
    if (startedRef.current) return // poll + start button can both fire this
    startedRef.current = true
    onStarted()
  }, [onStarted])

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const state = await api.getRoom(session.roomCode, session.token)
        if (cancelled) return
        setRoom(state)
        if (state.status === 'in_progress') handleStarted()
      } catch (err) {
        if (cancelled) return
        // Room evaporated or our token is no good — the lobby is over for us.
        if (err.status === 404 || err.status === 401) {
          onLeft('That room is no longer available.')
        }
        // transient network errors: keep polling silently
      }
    }

    poll()
    const timer = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [session.roomCode, session.token, handleStarted, onLeft])

  const me = room?.players.find((p) => p.player_id === session.playerId)
  const everyoneReady = room ? room.players.every((p) => p.ready) : false
  const canStart = room ? room.players.length >= 2 && everyoneReady : false

  async function toggleReady() {
    if (!me) return
    setBusy(true)
    setError(null)
    try {
      const state = await api.setReady(session.roomCode, session.token, !me.ready)
      setRoom(state)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function startGame() {
    setBusy(true)
    setError(null)
    try {
      await api.startGame(session.roomCode, session.token)
      handleStarted()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  async function leaveRoom() {
    setBusy(true)
    try {
      await api.leaveRoom(session.roomCode, session.token)
    } catch {
      // leaving a dead room is still leaving
    }
    onLeft(null)
  }

  if (!room) {
    return (
      <main className="screen lobby">
        <p className="loading">Loading room…</p>
      </main>
    )
  }

  return (
    <main className="screen lobby">
      <header className="lobby-header">
        <span className="lobby-label">Room code</span>
        <div className="lobby-code" data-testid="room-code">{room.code}</div>
        <p className="lobby-hint">Friends join with this code · {room.players.length}/{room.max_players} players</p>
      </header>

      {error && <p className="form-error" role="alert">{error}</p>}

      <ul className="lobby-players">
        {room.players.map((player) => (
          <li key={player.player_id} className="lobby-player">
            <span className="avatar" aria-hidden="true">{player.name.charAt(0).toUpperCase()}</span>
            <span className="lobby-player-name">
              {player.name}
              {player.is_host && <span className="tag tag--host">host</span>}
              {player.player_id === session.playerId && <span className="tag">you</span>}
            </span>
            <span className={player.ready ? 'ready ready--yes' : 'ready'}>
              {player.ready ? 'Ready' : 'Not ready'}
            </span>
          </li>
        ))}
      </ul>

      <div className="lobby-actions">
        <button className="button button--primary" type="button" disabled={busy || !me} onClick={toggleReady}>
          {me?.ready ? 'Unready' : "I'm ready"}
        </button>

        {me?.is_host && (
          <button
            className={canStart ? 'button button--gold' : 'button'}
            type="button"
            disabled={busy}
            onClick={startGame}
          >
            Start game
          </button>
        )}
        {me?.is_host && !canStart && (
          <p className="lobby-hint">
            {room.players.length < 2 ? 'Need at least 2 players.' : 'Waiting for everyone to ready up.'}
          </p>
        )}
        {!me?.is_host && <p className="lobby-hint">Waiting for the host to start…</p>}

        <button className="button button--quiet" type="button" disabled={busy} onClick={leaveRoom}>
          Leave room
        </button>
      </div>
    </main>
  )
}
