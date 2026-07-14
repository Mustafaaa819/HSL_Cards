from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket-test"])


@router.websocket("/ws/test")
async def websocket_echo(websocket: WebSocket) -> None:
    """Scaffolding-only echo endpoint. Real game rooms will live at /ws/room/{room_id}."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        pass
