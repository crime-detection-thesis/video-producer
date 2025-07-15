import cv2
import threading
import time
import asyncio

import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame
import websockets
import json
from collections import defaultdict
from fastapi import WebSocket
from app.incident_buffer import buffer_frame

import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

camera_viewers = defaultdict(int)

class SharedCameraStream:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        # self.cap = cv2.VideoCapture(rtsp_url)
        self.cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            raise RuntimeError(f"❌ No se pudo abrir RTSP: {rtsp_url}")
        self.latest_frame = None
        self.running = True
        self.lock = threading.Lock()
        self.finished = False

    def update(self):
        error_count = 0

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                error_count += 1
                if error_count >= 30:
                    print(f"❌ Fallo persistente en RTSP para {self.rtsp_url}")
                    self.running = False
                time.sleep(0.1)
                continue

            error_count = 0
            with self.lock:
                self.latest_frame = frame
            time.sleep(1 / 30)

        with self.lock:
            self.finished = True
            self.latest_frame = None
        self.cap.release()
        print(f"🛑 Captura detenida para {self.rtsp_url}")

    def stop(self):
        self.running = False

class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, shared_stream: SharedCameraStream, camera_id: int, inference_server_url: str, user_id: int, signal_ws: WebSocket):
        super().__init__()
        self.shared_stream = shared_stream
        self.camera_id = camera_id
        self.user_id = user_id
        self.inference_server_url = f'ws://{inference_server_url}/predict/{camera_id}'
        self.signal_ws = signal_ws
        camera_viewers[camera_id] += 1
        print(f"👤 Nuevo viewer para {camera_id}: {camera_viewers[camera_id]}")
        self.websocket = None

    async def send_frame_to_inference(self, frame: np.ndarray):
        if not self.websocket:
            try:
                print('🔌 Conectando al servidor de inferencia...')
                self.websocket = await websockets.connect(self.inference_server_url)
                init_msg = json.dumps({
                    "user_id": self.user_id,
                })
                await self.websocket.send(init_msg)
            except websockets.exceptions.WebSocketException as e:
                print(f"⚠️ Error al conectar con el servidor de inferencia: {e}")
                self.websocket = None
                return None
            except Exception as e:
                print(f"⚠️ Error inesperado al conectar con el servidor de inferencia: {e}")
                self.websocket = None
                return None

        try:
            _, frame_encoded = cv2.imencode('.jpg', frame)
            frame_bytes = frame_encoded.tobytes()

            await self.websocket.send(frame_bytes)

            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                labels_and_boxes = json.loads(response)
                return labels_and_boxes
            except asyncio.TimeoutError:
                print("⚠️ Timeout al recibir la respuesta del servidor de inferencia.")
                self.websocket.close()
                return None

        except Exception as e:
            print(f"⚠️ Error en la comunicación WebSocket con el servidor de inferencia: {e}")
            if self.websocket:
                self.websocket.close()
            return None

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        await asyncio.sleep(0.03)

        with self.shared_stream.lock:
            if self.shared_stream.finished:
                print(f"⚠️ Stream finalizado para {self.camera_id}, no se envía más video")
                raise asyncio.CancelledError("Stream finalizado")

            frame = self.shared_stream.latest_frame.copy() if self.shared_stream.latest_frame is not None else None

        if frame is None:
            await asyncio.sleep(0.1)
            return await self.recv()

        labels_and_boxes = await self.send_frame_to_inference(frame)

        if labels_and_boxes["detections"]:
            print('✅ Detección detectada')

            _, jpg = cv2.imencode(".jpg", frame)
            frame_bytes = jpg.tobytes()

            max_conf = max(d["confidence"] for d in labels_and_boxes["detections"])

            await buffer_frame(
                self.camera_id,
                self.user_id,
                frame_bytes,
                labels_and_boxes["detections"],
                max_conf,
            )

            try:
                await self.signal_ws.send_json({
                    "event": "detection",
                    "camera_id": self.camera_id,
                })
            except Exception as e:
                print(f"⚠️ Error al enviar detección al cliente: {e}")

            frame_with_boxes = self.draw_bounding_boxes(frame, labels_and_boxes)
        else:
            frame_with_boxes = frame

        rgb_frame = cv2.cvtColor(frame_with_boxes, cv2.COLOR_BGR2RGB)
        av_frame = VideoFrame.from_ndarray(rgb_frame, format="rgb24")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame

    def draw_bounding_boxes(self, frame: np.ndarray, labels_and_boxes):
        if labels_and_boxes["detections"]:
            for detection in labels_and_boxes['detections']:
                x1, y1, x2, y2 = detection['box']
                label = f'{detection["label"]} ({detection["confidence"] * 100:.1f}%)'
                color = (255, 0, 0)
                thickness = 2
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        return frame

    async def stop(self, camera_streams, camera_registry):
        print(f"🔌 Closing video track for camera {self.camera_id} stop")
        if self.websocket:
            try:
                print(f"🔌 Closing video track for camera {self.camera_id} websocket stop")
                await self.websocket.close()
            except Exception:
                pass
        
        if camera_viewers[self.camera_id] > 0:
            print(f"🔌 Closing video track for camera {self.camera_id} viewer stop")
            camera_viewers[self.camera_id] -= 1
            print(f" Viewers restantes para {self.camera_id}: {camera_viewers[self.camera_id]}")
            if camera_viewers[self.camera_id] == 0:
                print(f"🔌 Closing video track for camera {self.camera_id} viewer stop final")
                stop_camera_stream(self.camera_id, camera_streams, camera_registry)
                del camera_viewers[self.camera_id]

def start_camera_stream(camera_id, rtsp_url, stream_registry):
    try:
        shared_stream = SharedCameraStream(rtsp_url)
        t = threading.Thread(target=shared_stream.update, daemon=True)
        t.start()
        stream_registry[camera_id] = (shared_stream, t)
        print(f"✅ Hilo iniciado para {camera_id}")
        return True
    except Exception as e:
        print(f"❌ Error al iniciar cámara {camera_id}: {e}")
        if camera_id in stream_registry:
            del stream_registry[camera_id]
        return False

def stop_camera_stream(camera_id, camera_streams, camera_registry):
    if camera_id in camera_streams:
        shared_stream, thread = camera_streams[camera_id]
        shared_stream.stop()
        del camera_streams[camera_id]
    if camera_id in camera_registry:
        del camera_registry[camera_id]
    print(f" Recursos liberados para {camera_id}")


def get_video_track(camera_id, stream_registry, inference_server_url, user_id, signal_ws):
    shared_stream, _ = stream_registry[camera_id]
    return CameraVideoTrack(shared_stream, camera_id, inference_server_url, user_id, signal_ws)
