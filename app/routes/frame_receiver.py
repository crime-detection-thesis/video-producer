import asyncio
import contextlib
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.shared_frame_buffer import SharedFrameBuffer
from app.services.detection import DetectionService
from app.config import INFERENCE_SERVER_URL

router = APIRouter()

camera_buffers: dict[int, SharedFrameBuffer] = {}
detection_services: dict[int, DetectionService] = {}
processing_tasks: dict[int, asyncio.Task] = {}

@router.websocket("/ws/{camera_id}")
async def receive_camera_frames(websocket: WebSocket, camera_id: int):
    print(f'🔌 Accepting WebSocket connection for camera {camera_id}')
    await websocket.accept()

    buffer = SharedFrameBuffer()
    camera_buffers[camera_id] = buffer

    detection_service = DetectionService(INFERENCE_SERVER_URL, user_id=camera_id)
    detection_services[camera_id] = detection_service

    frame_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)

    async def process_frames():
        while True:
            try:
                jpg_bytes = await frame_queue.get()
            except asyncio.CancelledError:
                break

            frame_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            try:
                result = await detection_service.detect(frame)
            except Exception as e:
                print(f"⚠️ Detection error cam {camera_id}: {e}")
                continue

            frame_with_boxes = DetectionService.draw_boxes(frame, result["detections"])
            buffer.update_frame(frame_with_boxes)

    processing_tasks[camera_id] = asyncio.create_task(process_frames())

    try:
        while True:
            jpg_bytes = await websocket.receive_bytes()
            if frame_queue.full():
                try:
                    _ = frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await frame_queue.put(jpg_bytes)
    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected for camera {camera_id}")
    except Exception as e:
        print(f"🚨 Error in camera {camera_id} WebSocket: {e}")
    finally:
        task = processing_tasks.pop(camera_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        buffer.finished = True
        camera_buffers.pop(camera_id, None)
        detection_services.pop(camera_id, None)
