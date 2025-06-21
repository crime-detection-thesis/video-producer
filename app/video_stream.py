import cv2
import threading
import time

import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame
import asyncio
import websockets
import json
from collections import defaultdict
# from app.main import camera_streams, camera_registry

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
    def __init__(self, shared_stream: SharedCameraStream, camera_name: str, inference_server_url: str):
        super().__init__()
        self.shared_stream = shared_stream
        self.camera_name = camera_name
        self.inference_server_url = inference_server_url
        camera_viewers[camera_name] += 1
        print(f"👤 Nuevo viewer para {camera_name}: {camera_viewers[camera_name]}")
        self.websocket = None

    async def send_frame_to_inference(self, frame: np.ndarray):
        if not self.websocket:
            try:
                print('🔌 Conectando al servidor de inferencia...')
                self.websocket = await websockets.connect(self.inference_server_url)
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
                print(f"⚠️ Stream finalizado para {self.camera_name}, no se envía más video")
                raise asyncio.CancelledError("Stream finalizado")

            frame = self.shared_stream.latest_frame.copy() if self.shared_stream.latest_frame is not None else None

        if frame is None:
            await asyncio.sleep(0.1)
            return await self.recv()

        labels_and_boxes = await self.send_frame_to_inference(frame)

        if labels_and_boxes:
            frame_with_boxes = self.draw_bounding_boxes(frame, labels_and_boxes)
        else:
            frame_with_boxes = frame

        frame = cv2.cvtColor(frame_with_boxes, cv2.COLOR_BGR2RGB)
        av_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame

    def draw_bounding_boxes(self, frame: np.ndarray, labels_and_boxes):
        if labels_and_boxes:
            for detection in labels_and_boxes['detections']:
                x1, y1, x2, y2 = detection['box']
                label = f'{detection["label"]} ({detection["confidence"] * 100:.1f}%)'
                color = (255, 0, 0)
                thickness = 2
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        return frame

    async def stop(self, camera_streams, camera_registry):
        camera_viewers[self.camera_name] -= 1
        print(f"👁️‍🗨️ Viewers restantes para {self.camera_name}: {camera_viewers[self.camera_name]}")
        if camera_viewers[self.camera_name] <= 0:
            stop_camera_stream(self.camera_name, camera_streams, camera_registry)
            del camera_viewers[self.camera_name]

def start_camera_stream(camera_name, rtsp_url, stream_registry):
    shared_stream = SharedCameraStream(rtsp_url)
    t = threading.Thread(target=shared_stream.update, daemon=True)
    t.start()
    stream_registry[camera_name] = (shared_stream, t)
    print(f"🧵 Hilo iniciado para {camera_name}")


def stop_camera_stream(camera_name, camera_streams, camera_registry):
    if camera_name in camera_streams:
        shared_stream, thread = camera_streams[camera_name]
        shared_stream.stop()
        del camera_streams[camera_name]
    if camera_name in camera_registry:
        del camera_registry[camera_name]
    print(f"🗑️ Recursos liberados para {camera_name}")


def get_video_track(camera_name, stream_registry, inference_server_url):
    shared_stream, _ = stream_registry[camera_name]
    return CameraVideoTrack(shared_stream, camera_name, inference_server_url)
