// sessionStorage (not localStorage) on purpose: each browser tab is its own
// player, which is how the friend group will test locally and how Playwright
// drives multiple players — and the token survives a reload for reconnects.
const STORAGE_KEY = 'hsl-cards-session'

export function loadSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const session = JSON.parse(raw)
    if (!session.roomCode || !session.playerId || !session.token) return null
    return session
  } catch {
    return null // corrupt JSON in storage — treat as no session
  }
}

export function saveSession(session) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession() {
  sessionStorage.removeItem(STORAGE_KEY)
}
