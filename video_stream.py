import cv2
import threading
import time
from aiortc import VideoStreamTrack
from av import VideoFrame
import asyncio
from collections import defaultdict

camera_viewers = defaultdict(int)

class SharedCameraStream:
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.cap = cv2.VideoCapture(rtsp_url)
        if not self.cap.isOpened():
            raise RuntimeError(f"❌ No se pudo abrir RTSP: {rtsp_url}")
        self.latest_frame = None
        self.running = True
        self.lock = threading.Lock()
        self.finished = False

    def update(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue
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
    def __init__(self, shared_stream: SharedCameraStream, camera_name: str):
        super().__init__()
        self.shared_stream = shared_stream
        self.camera_name = camera_name
        camera_viewers[camera_name] += 1
        print(f"👤 Nuevo viewer para {camera_name}: {camera_viewers[camera_name]}")

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

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        av_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame

    async def stop(self):
        camera_viewers[self.camera_name] -= 1
        print(f"👁️‍🗨️ Viewers restantes para {self.camera_name}: {camera_viewers[self.camera_name]}")
        if camera_viewers[self.camera_name] <= 0:
            stop_camera_stream(self.camera_name)
            del camera_viewers[self.camera_name]

def start_camera_stream(camera_name, rtsp_url, stream_registry):
    shared_stream = SharedCameraStream(rtsp_url)
    t = threading.Thread(target=shared_stream.update, daemon=True)
    t.start()
    stream_registry[camera_name] = (shared_stream, t)
    print(f"🧵 Hilo iniciado para {camera_name}")

def stop_camera_stream(camera_name):
    from main import camera_streams, camera_registry
    if camera_name in camera_streams:
        shared_stream, thread = camera_streams[camera_name]
        shared_stream.stop()
        del camera_streams[camera_name]
    if camera_name in camera_registry:
        del camera_registry[camera_name]
    print(f"🗑️ Recursos liberados para {camera_name}")

def get_video_track(camera_name, stream_registry):
    shared_stream, _ = stream_registry[camera_name]
    return CameraVideoTrack(shared_stream, camera_name)


