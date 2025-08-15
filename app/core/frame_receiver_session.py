import asyncio
import contextlib
import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect
from app.services.buffer import buffer_frame
from app.shared_state import camera_user_map, camera_buffers
from app.inference.send_detection import send_detection_event

class FrameReceiverSession:
    def __init__(self, websocket: WebSocket, camera_id: int, buffer, detection_service, detection_services, processing_tasks):
        self.websocket = websocket
        self.camera_id = camera_id
        self.buffer = buffer
        self.detection_service = detection_service
        self.detection_services = detection_services
        self.processing_tasks = processing_tasks
        self.frame_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)

    async def run(self):
        await self.websocket.accept()
        self.processing_tasks[self.camera_id] = asyncio.create_task(self.process_frames())
        try:
            await self._receive_frames()
        except WebSocketDisconnect:
            print(f"❌ WebSocket disconnected for camera {self.camera_id}")
        except Exception as e:
            print(f"🚨 Error in camera {self.camera_id} WebSocket: {e}")
        finally:
            await self._cleanup()

    async def _receive_frames(self):
        while True:
            jpg_bytes = await self.websocket.receive_bytes()
            if self.frame_queue.full():
                try:
                    _ = self.frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self.frame_queue.put(jpg_bytes)

    async def process_frames(self):
        while True:
            try:
                jpg_bytes = await self.frame_queue.get()
            except asyncio.CancelledError:
                break

            frame_array = np.frombuffer(jpg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            try:
                result = await self.detection_service.detect(frame)
            except Exception as e:
                print(f"⚠️ Detection error cam {self.camera_id}: {e}")
                continue

            frame_with_boxes = self.detection_service.draw_boxes(frame, result["detections"])
            
            if result["detections"]:
                try:
                    _, jpg_buffer = cv2.imencode('.jpg', frame)
                    jpg_bytes = jpg_buffer.tobytes()
                    max_confidence = max(d["confidence"] for d in result["detections"]) if result["detections"] else 0
                    user_id = camera_user_map.get(self.camera_id, str(self.camera_id))
                    await buffer_frame(
                        camera_id=str(self.camera_id),
                        user_id=user_id,
                        frame_bytes=jpg_bytes,
                        detections=result["detections"],
                        confidence=max_confidence
                    )
                    print(f"✅ Incident buffered for camera {self.camera_id}")
                    await send_detection_event(self.camera_id)
                    print(f'✅ Detection event sent for camera {self.camera_id}')
                except Exception as e:
                    print(f"⚠️ Error buffering frame for incident: {e}")
            
            self.buffer.update_frame(frame_with_boxes)

    async def _cleanup(self):
        task = self.processing_tasks.pop(self.camera_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self.detection_services[self.camera_id].client.close()
        self.buffer.finished = True
        camera_buffers.pop(self.camera_id, None)
        self.detection_services.pop(self.camera_id, None)
