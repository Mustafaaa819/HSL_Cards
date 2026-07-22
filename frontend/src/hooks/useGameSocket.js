import { useCallback, useEffect, useRef, useState } from 'react'
import { gameWsUrl } from '../config.js'

// Close codes from docs/WS_PROTOCOL.md. Fatal ones mean this token/room can
// never work, so retrying would loop forever against the same rejection.
const FATAL_CODES = new Set([4000, 4001, 4004])
const CODE_GAME_NOT_STARTED = 4002
const CODE_SUPERSEDED = 4008

const RECONNECT_MAX_DELAY_MS = 8000

// statuses: connecting | connected | reconnecting | superseded | dead
export function useGameSocket(roomCode, token, handlers) {
  const [gameState, setGameState] = useState(null)
  const [status, setStatus] = useState('connecting')

  // Handlers live in a ref so a new callback identity from a parent render
  // doesn't tear down and rebuild a perfectly good socket.
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const socketRef = useRef(null)
  const attemptRef = useRef(0)
  const timerRef = useRef(null)
  const stoppedRef = useRef(false)

  const connect = useCallback(() => {
    const socket = new WebSocket(gameWsUrl(roomCode))
    socketRef.current = socket

    // First frame must be the auth token, per protocol.
    socket.onopen = () => socket.send(JSON.stringify({ token }))

    socket.onmessage = (frame) => {
      let message
      try {
        message = JSON.parse(frame.data)
      } catch {
        return // server never sends non-JSON; ignore rather than crash
      }
      if (message.type === 'state') {
        attemptRef.current = 0
        setStatus('connected')
        setGameState(message.state)
        if (message.event) handlersRef.current?.onEvent?.(message.event, message.state)
      } else if (message.type === 'chat') {
        handlersRef.current?.onChat?.(message.message)
      } else if (message.type === 'chat_history') {
        // Always arrives right after the connect snapshot, empty log
        // included — so this replaces the client's log rather than merging.
        handlersRef.current?.onChatHistory?.(message.messages ?? [])
      } else if (message.type === 'error') {
        // Whole payload, not just the text: `code` and `card` are what let
        // the UI highlight the exact card the server refused.
        handlersRef.current?.onServerError?.({
          message: message.message,
          code: message.code ?? 'illegal_move',
          card: message.card ?? null,
        })
      }
    }

    socket.onclose = (event) => {
      if (socketRef.current !== socket) return // replaced by a newer socket of ours
      socketRef.current = null
      if (stoppedRef.current) return

      if (event.code === CODE_SUPERSEDED) {
        // Another tab/device took over with this token. Auto-reconnecting
        // here would make the two connections fight forever, so we stop and
        // let the player explicitly reclaim the session.
        setStatus('superseded')
        return
      }
      if (FATAL_CODES.has(event.code) || event.code === CODE_GAME_NOT_STARTED) {
        setStatus('dead')
        handlersRef.current?.onFatalClose?.(event.code, event.reason)
        return
      }
      setStatus('reconnecting')
      const delay = Math.min(1000 * 2 ** attemptRef.current, RECONNECT_MAX_DELAY_MS)
      attemptRef.current += 1
      timerRef.current = setTimeout(connect, delay)
    }
  }, [roomCode, token])

  useEffect(() => {
    stoppedRef.current = false
    attemptRef.current = 0
    setStatus('connecting')
    connect()
    return () => {
      stoppedRef.current = true
      clearTimeout(timerRef.current)
      const socket = socketRef.current
      socketRef.current = null
      socket?.close()
    }
  }, [connect])

  const sendAction = useCallback((action) => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      // Shaped like a server error so the toast has one payload type to
      // render. "offline" is client-only — it never comes over the wire.
      handlersRef.current?.onServerError?.({
        message: 'Not connected right now — reconnecting…',
        code: 'offline',
        card: null,
      })
      return
    }
    socket.send(JSON.stringify(action))
  }, [])

  // Manual "resume here" after being superseded by another tab.
  const reclaim = useCallback(() => {
    attemptRef.current = 0
    setStatus('connecting')
    connect()
  }, [connect])

  return { gameState, status, sendAction, reclaim }
}
