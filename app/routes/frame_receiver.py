import base64
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.shared_frame_buffer import SharedFrameBuffer
from app.services.detection import DetectionService
from app.config import INFERENCE_SERVER_URL

router = APIRouter()
camera_buffers: dict[int, SharedFrameBuffer] = {}
detection_services: dict[int, DetectionService] = {}


@router.websocket("/ws/{camera_id}")
async def receive_camera_frames(websocket: WebSocket, camera_id: int):
    print('🔌 Accepting WebSocket connection for camera from receiver', camera_id)
    await websocket.accept()

    buffer = SharedFrameBuffer()
    camera_buffers[camera_id] = buffer

    detection_service = DetectionService(INFERENCE_SERVER_URL, user_id=camera_id)
    detection_services[camera_id] = detection_service

    try:
        while True:
            data = await websocket.receive_text()
            jpg_bytes = base64.b64decode(data)
            jpg_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(jpg_array, cv2.IMREAD_COLOR)

            if frame is not None:
                result = await detection_service.detect(frame)
                frame_with_boxes = DetectionService.draw_boxes(frame, result["detections"])
                buffer.update_frame(frame_with_boxes)
    except WebSocketDisconnect:
        print(f"WebSocket for camera {camera_id} disconnected.")
    except Exception as e:
        print(f"Error in camera {camera_id} WebSocket: {e}")
    finally:
        buffer.finished = True
        camera_buffers.pop(camera_id, None)
        detection_services.pop(camera_id, None)
