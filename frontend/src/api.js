import { apiUrl } from './config.js'

export class ApiError extends Error {
  constructor(message, status, options) {
    super(message, options)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, { method = 'GET', token, body } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['X-Player-Token'] = token

  let response
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    throw new ApiError('Could not reach the server', 0, { cause: err })
  }

  let payload = null
  try {
    payload = await response.json()
  } catch (err) {
    if (response.ok) throw new ApiError('Server sent a malformed response', response.status, { cause: err })
  }

  if (!response.ok) {
    throw new ApiError(detailToMessage(payload?.detail, response.status), response.status)
  }
  return payload
}

// FastAPI errors come back as {"detail": "..."} for our RoomError mapping,
// but as {"detail": [{...validation objects}]} for 422s — flatten both.
function detailToMessage(detail, status) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === 'string') {
    return detail[0].msg.replace(/^Value error, /, '')
  }
  return `Request failed (${status})`
}

export const api = {
  createRoom: (name) => request('/rooms', { method: 'POST', body: { name } }),
  joinRoom: (code, name) => request(`/rooms/${code}/join`, { method: 'POST', body: { name } }),
  getRoom: (code, token) => request(`/rooms/${code}`, { token }),
  setReady: (code, token, ready) => request(`/rooms/${code}/ready`, { method: 'PUT', token, body: { ready } }),
  leaveRoom: (code, token) => request(`/rooms/${code}/leave`, { method: 'POST', token }),
  startGame: (code, token) => request(`/rooms/${code}/start`, { method: 'POST', token }),
}
