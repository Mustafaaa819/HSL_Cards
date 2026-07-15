import { useState } from 'react'
import { api } from '../api.js'

// Create a room or join one by code — Phase 2 REST only, no sockets here.
export default function EntryScreen({ onEnterRoom, notice }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.createRoom(name.trim())
      onEnterRoom(result)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  async function handleJoin(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.joinRoom(code.trim().toUpperCase(), name.trim())
      onEnterRoom(result)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <main className="screen entry">
      <h1 className="entry-title">HSL Cards</h1>
      <p className="entry-tagline">Lose your cards before your friends do.</p>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}

      <label className="field">
        <span className="field-label">Your name</span>
        <input
          className="field-input"
          type="text"
          maxLength={20}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Mustafa"
          autoComplete="off"
        />
      </label>

      <button
        className="button button--primary"
        type="button"
        disabled={busy || name.trim() === ''}
        onClick={handleCreate}
      >
        Create a room
      </button>

      <div className="entry-divider" aria-hidden="true"><span>or join a friend</span></div>

      <form className="entry-join" onSubmit={handleJoin}>
        <input
          className="field-input field-input--code"
          type="text"
          maxLength={5}
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="CODE"
          autoComplete="off"
        />
        <button
          className="button"
          type="submit"
          disabled={busy || name.trim() === '' || code.trim().length < 5}
        >
          Join
        </button>
      </form>
    </main>
  )
}
