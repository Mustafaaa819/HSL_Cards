"""Per-room WebSocket connection registry.

Tracks at most ONE live socket per (room, player). A reconnecting player
replaces their previous socket — `register` hands the old one back so the
caller can close it. All methods are synchronous and never await, so on
the single event loop each operation is atomic (same stance as
rooms.manager).

Finished games keep their entries until every socket disconnects; like
the room store itself, nothing is ever swept in this prototype.
"""

from __future__ import annotations

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, WebSocket]] = {}

    def register(self, room_code: str, player_id: str, websocket: WebSocket) -> WebSocket | None:
        """Make `websocket` the player's live connection. Returns the socket
        it replaced (caller is responsible for closing it), or None."""
        connections = self._rooms.setdefault(room_code, {})
        previous = connections.get(player_id)
        connections[player_id] = websocket
        return previous

    def unregister(self, room_code: str, player_id: str, websocket: WebSocket) -> None:
        """Drop the player's connection — but only if it still IS this socket,
        so a superseded socket's cleanup never evicts its replacement."""
        connections = self._rooms.get(room_code)
        if connections and connections.get(player_id) is websocket:
            del connections[player_id]
            if not connections:
                del self._rooms[room_code]

    def connections(self, room_code: str) -> dict[str, WebSocket]:
        """Snapshot of player_id -> socket for a room (copy, safe to iterate
        while sockets register/unregister mid-broadcast)."""
        return dict(self._rooms.get(room_code, {}))


# Single shared instance for the app's lifetime, like rooms.room_manager.
connection_hub = ConnectionHub()
