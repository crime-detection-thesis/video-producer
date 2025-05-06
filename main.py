from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from video_stream import get_video_track, start_camera_stream
app = FastAPI()
camera_registry = {}
camera_streams = {}
pcs = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ice_servers = [
    RTCIceServer(
        urls="turn:openrelay.metered.ca:80",
        username="openrelayproject",
        credential="openrelayproject"
    ),
]
config = RTCConfiguration(iceServers=ice_servers)

class CameraConnectionRequest(BaseModel):
    camera_name: str
    rtsp_url: str

class SDPRequest(BaseModel):
    camera_name: str
    sdp: str
    type: str

@app.post("/connect-camera")
async def connect_camera(camera: CameraConnectionRequest):
    if camera.camera_name not in camera_streams:
        start_camera_stream(camera.camera_name, camera.rtsp_url, camera_streams)
        camera_registry[camera.camera_name] = camera.rtsp_url
        print(f"✅ Cámara registrada: {camera.camera_name} -> {camera.rtsp_url}")
    return {"message": "Camera registered successfully."}

@app.post("/negotiate")
async def negotiate_webrtc(data: SDPRequest):
    camera_name = data.camera_name
    if camera_name not in camera_streams:
        return {"error": "Camera not registered or not started."}

    offer = RTCSessionDescription(sdp=data.sdp, type=data.type)
    pc = RTCPeerConnection(configuration=config)
    pcs.add(pc)

    video_track = get_video_track(camera_name, camera_streams)

    pc.addTrack(video_track)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"📡 Estado conexión {camera_name}: {pc.connectionState}")
        if pc.connectionState in ["failed", "closed", "disconnected"]:
            print(f"❌ Conexión cerrada para {camera_name}")
            await pc.close()
            pcs.discard(pc)
            await video_track.stop()

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    print(f"🎥 Transmisión creada: {camera_name}")

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }

