import { useEffect, useState } from 'react'
import './App.css'
import { api } from './api.js'
import { clearSession, loadSession, saveSession } from './session.js'
import EntryScreen from './screens/EntryScreen.jsx'
import LobbyScreen from './screens/LobbyScreen.jsx'
import GameScreen from './screens/GameScreen.jsx'

// stages: resolving (stored session, checking where it belongs) | entry | lobby | game
export default function App() {
  const [session, setSession] = useState(loadSession)
  const [stage, setStage] = useState(session ? 'resolving' : 'entry')
  const [notice, setNotice] = useState(null)
  // True only when the lobby just told us a match started — the one signal
  // that distinguishes a genuine fresh start (deal animation plays) from a
  // reload/reconnect resolving straight into 'game' (it must not).
  const [freshStart, setFreshStart] = useState(false)

  // A reload mid-session (common on phones) lands here with a stored token:
  // ask the server whether that room is still in the lobby or already live.
  useEffect(() => {
    if (stage !== 'resolving') return
    let cancelled = false
    api
      .getRoom(session.roomCode, session.token)
      .then((room) => {
        if (!cancelled) setStage(room.status === 'in_progress' ? 'game' : 'lobby')
      })
      .catch(() => {
        if (cancelled) return
        clearSession()
        setSession(null)
        setStage('entry')
      })
    return () => {
      cancelled = true
    }
  }, [stage, session])

  function enterRoom(result) {
    const next = {
      roomCode: result.room_code,
      playerId: result.player_id,
      token: result.token,
    }
    saveSession(next)
    setSession(next)
    setNotice(null)
    setStage('lobby')
  }

  function leaveToEntry(message) {
    clearSession()
    setSession(null)
    setNotice(message ?? null)
    setFreshStart(false)
    setStage('entry')
  }

  // Terminal socket closes, per docs/WS_PROTOCOL.md: 4002 means the room
  // exists but isn't started (send them back to the lobby); the rest mean
  // this session can never connect, so it gets discarded.
  function handleFatalClose(code) {
    if (code === 4002) {
      setStage('lobby')
    } else {
      leaveToEntry('Lost access to the game — join or create a new room.')
    }
  }

  if (stage === 'resolving') {
    return (
      <main className="screen">
        <p className="loading">Loading…</p>
      </main>
    )
  }
  if (stage === 'lobby') {
    return (
      <LobbyScreen
        session={session}
        onStarted={() => {
          setFreshStart(true)
          setStage('game')
        }}
        onLeft={leaveToEntry}
      />
    )
  }
  if (stage === 'game') {
    return (
      <GameScreen
        session={session}
        dealOnEntry={freshStart}
        onLeave={() => leaveToEntry(null)}
        onFatalClose={handleFatalClose}
      />
    )
  }
  return <EntryScreen onEnterRoom={enterRoom} notice={notice} />
}
