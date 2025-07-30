from fastapi import APIRouter, WebSocket
from app.core.webrtc_signaling import handle_signaling

router = APIRouter()

@router.websocket("/ws/{camera_id}")
async def websocket_endpoint(websocket: WebSocket, camera_id: int):
    await handle_signaling(websocket, camera_id)
