// In dev, the frontend (Vite, :5173) and backend (uvicorn, :8000) run as
// separate servers, so the backend origin must be set via .env.development.local.
// In production the frontend is served by the same FastAPI process as the
// backend, so we can derive everything from the current page's origin.
const backendOrigin = import.meta.env.VITE_BACKEND_URL || window.location.origin

export function apiUrl(path) {
  return `${backendOrigin}${path}`
}

export function gameWsUrl(roomCode) {
  const origin = new URL(backendOrigin)
  const protocol = origin.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${origin.host}/ws/${roomCode}`
}
