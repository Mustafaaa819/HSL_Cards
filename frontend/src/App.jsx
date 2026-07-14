import { useEffect, useRef, useState } from 'react'
import './App.css'

// In dev, the frontend (Vite, :5173) and backend (uvicorn, :8000) run as
// separate servers, so the WS URL must be set explicitly via .env.local.
// In production the frontend is served by the same FastAPI process as the
// backend, so we can derive the WS URL from the current page's origin.
function resolveWsUrl() {
  const envUrl = import.meta.env.VITE_WS_URL
  if (envUrl) return envUrl

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/test`
}

export default function App() {
  const [status, setStatus] = useState('connecting')
  const [draft, setDraft] = useState('')
  const [log, setLog] = useState([])
  const socketRef = useRef(null)

  useEffect(() => {
    const socket = new WebSocket(resolveWsUrl())
    socketRef.current = socket

    socket.onopen = () => setStatus('connected')
    socket.onclose = () => setStatus('disconnected')
    socket.onerror = () => setStatus('error')
    socket.onmessage = (event) => {
      setLog((prev) => [...prev, { direction: 'received', text: event.data }])
    }

    return () => socket.close()
  }, [])

  function sendMessage() {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN || draft.trim() === '') return

    socket.send(draft)
    setLog((prev) => [...prev, { direction: 'sent', text: draft }])
    setDraft('')
  }

  return (
    <main className="page">
      <h1 className="title">WebSocket Echo Test</h1>
      <p className={`status status--${status}`}>{status}</p>

      <div className="log" aria-live="polite">
        {log.length === 0 && <p className="log-empty">No messages yet.</p>}
        {log.map((entry, i) => (
          <div key={i} className={`log-entry log-entry--${entry.direction}`}>
            <span className="log-label">{entry.direction === 'sent' ? 'sent' : 'echoed'}</span>
            <span className="log-text">{entry.text}</span>
          </div>
        ))}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          sendMessage()
        }}
      >
        <input
          className="composer-input"
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type a message"
          disabled={status !== 'connected'}
        />
        <button className="composer-send" type="submit" disabled={status !== 'connected'}>
          Send
        </button>
      </form>
    </main>
  )
}
