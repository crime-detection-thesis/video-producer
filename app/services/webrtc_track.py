from aiortc import VideoStreamTrack
from av import VideoFrame
import asyncio
from app.routes.frame_receiver import camera_buffers
from app.utils.gateway_control import stop_gateway_stream

camera_viewers = {}

class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, camera_id: int):
        super().__init__()
        self.camera_id = camera_id
        camera_viewers[camera_id] = camera_viewers.get(camera_id, 0) + 1
        print(f"👤 Viewer joined camera {self.camera_id} — total: {camera_viewers[self.camera_id]}")

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        while True:
            buffer = camera_buffers.get(self.camera_id)
            if buffer:
                frame = buffer.get_latest_frame()
                if frame is not None:
                    video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
                    video_frame.pts = pts
                    video_frame.time_base = time_base
                    return video_frame
            await asyncio.sleep(0.01)

    def stop(self):
        print(f"❌ Viewer left camera {self.camera_id}")
        if self.camera_id in camera_viewers:
            camera_viewers[self.camera_id] -= 1
            if camera_viewers[self.camera_id] <= 0:
                print(f"🛑 No more viewers for camera {self.camera_id}, stopping stream...")
                asyncio.create_task(stop_gateway_stream(self.camera_id))
                del camera_viewers[self.camera_id]
        super().stop()
