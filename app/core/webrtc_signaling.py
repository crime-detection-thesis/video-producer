from fastapi import WebSocket

from app.core.signaling_session import WebRTCSignalingSession


async def handle_signaling(ws: WebSocket, camera_id: int):
    session = WebRTCSignalingSession(ws, camera_id)
    await session.run()
