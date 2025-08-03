from fastapi import APIRouter, WebSocket
from app.services.shared_frame_buffer import SharedFrameBuffer
from app.services.detection import DetectionService
from app.config import INFERENCE_SERVER_URL
from app.shared_state import camera_buffers
from app.core.frame_receiver_session import FrameReceiverSession


router = APIRouter()

detection_services: dict[int, DetectionService] = {}
processing_tasks: dict[int, object] = {}

@router.websocket("/ws/{camera_id}")
async def receive_camera_frames(websocket: WebSocket, camera_id: int):
    print(f'🔌 Accepting WebSocket connection for camera {camera_id}')
    buffer = SharedFrameBuffer()
    camera_buffers[camera_id] = buffer
    detection_service = DetectionService(INFERENCE_SERVER_URL, camera_id)
    detection_services[camera_id] = detection_service

    session = FrameReceiverSession(
        websocket=websocket,
        camera_id=camera_id,
        buffer=buffer,
        detection_service=detection_service,
        detection_services=detection_services,
        processing_tasks=processing_tasks
    )
    await session.run()
