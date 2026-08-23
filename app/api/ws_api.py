from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["results"])


@router.websocket("/ws/results")
async def ws_results(
    websocket: WebSocket,
    camera_id: str | None = None,
) -> None:
    runtime = websocket.app.state.runtime
    subscriber = await runtime.result_channels.subscribe(websocket, camera_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        runtime.result_channels.unsubscribe(subscriber)
    except Exception:
        runtime.result_channels.unsubscribe(subscriber)
