"""Per-room AFK turn clock.

One asyncio task per room, holding at most one armed timer at a time. When
it fires, the caller-supplied callback forces a move for whoever's turn it
is and re-arms for the next player — so a table with several AFK players
keeps advancing rather than stalling on the first one.

Deliberately knows nothing about the engine or the WebSocket layer: it only
sleeps and calls back. The *policy* (which move gets forced) lives in
routers.game_ws, next to the other engine translation.

The clock is driven off the room, not off a socket: a player who closed
their tab entirely still gets timed out, which is the whole point.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.rooms import Room

TURN_TIMEOUT_SECONDS = 25.0

OnTimeout = Callable[[Room], Awaitable[None]]


class TurnClock:
    def __init__(self, timeout_seconds: float = TURN_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        # Monotonic deadline per room, so state payloads can tell clients how
        # long the current turn has left (see sync.serializer). Monotonic, not
        # wall-clock: payloads carry *remaining seconds*, never a timestamp,
        # so client/server clock skew can't distort the countdown.
        self._deadlines: dict[str, float] = {}

    def arm(self, room: Room, on_timeout: OnTimeout) -> None:
        """(Re)start the clock for the room's current turn, cancelling any
        timer left over from the previous one. A finished or unstarted game
        gets no timer — there is no turn left to run out."""
        self.cancel(room.code)
        if room.game is None or room.game.game_over:
            return
        self._deadlines[room.code] = time.monotonic() + self._timeout
        self._tasks[room.code] = asyncio.create_task(self._run(room, on_timeout))

    def arm_if_idle(self, room: Room, on_timeout: OnTimeout) -> None:
        """Arm only if this room has no timer running. Used on connect, where
        re-arming unconditionally would let a player dodge their own clock by
        flapping their socket."""
        if room.code not in self._tasks:
            self.arm(room, on_timeout)

    def cancel(self, room_code: str) -> None:
        self._deadlines.pop(room_code, None)
        task = self._tasks.pop(room_code, None)
        if task is not None:
            task.cancel()

    def is_armed(self, room_code: str) -> bool:
        return room_code in self._tasks

    def remaining(self, room_code: str) -> float | None:
        """Seconds until the current turn is forced, or None if no timer is
        running (game over, or no player has connected yet)."""
        deadline = self._deadlines.get(room_code)
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    async def _run(self, room: Room, on_timeout: OnTimeout) -> None:
        await asyncio.sleep(self._timeout)
        # Drop the handle BEFORE the callback: it will arm the next turn's
        # timer, and a stale entry here would make that call cancel it.
        self._tasks.pop(room.code, None)
        self._deadlines.pop(room.code, None)
        await on_timeout(room)


# Single shared instance for the app's lifetime, like connection_hub.
turn_clock = TurnClock()
