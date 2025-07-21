import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
)
from app.schemas import CameraConnectionRequest
from app.video_stream import get_video_track, start_camera_stream
from app.constants import INFERENCE_SERVER_URL
from fastapi import HTTPException
import cv2


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
    RTCIceServer(urls="stun:stun.l.google.com:19302"),
    RTCIceServer(
        urls="turn:openrelay.metered.ca:80",
        username="openrelayproject",
        credential="openrelayproject",
    ),
]
config = RTCConfiguration(iceServers=ice_servers)

@app.post("/connect-camera")
async def connect_camera(request: CameraConnectionRequest):
    camera_id = request.camera_id
    rtsp_url  = request.rtsp_url

    if camera_id in camera_streams:
        return {"status": "already_running"}

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        raise HTTPException(
            status_code=400,
            detail="No se pudo conectar a la cámara: URL RTSP inválida o inaccesible."
        )
    cap.release()

    start_camera_stream(camera_id, rtsp_url, camera_streams)
    camera_registry[camera_id] = rtsp_url
    return {"status": "started", "camera_id": camera_id}


@app.websocket("/ws/{camera_id}")
async def signaling_ws(websocket: WebSocket, camera_id: int):
    await websocket.accept()

    if camera_id not in camera_streams:
        await websocket.send_json({"error": "Error al conectar la cámara"})
        await websocket.close(code=4404)
        return

    try:
        init = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4001)
        return

    user_id = init.get("user_id")
    sdp     = init.get("sdp")
    typ     = init.get("type")
    if not user_id or not sdp or typ != "offer":
        await websocket.close(code=4002)
        return
    
    pc = RTCPeerConnection(configuration=config)
    video_track = get_video_track(
        camera_id,
        camera_streams,
        INFERENCE_SERVER_URL,
        user_id,
        websocket
    )
    pc.addTrack(video_track)

    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await websocket.send_json({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    except Exception as e:
        print(f"Error en SDP handshake: {e}")
        await websocket.close(code=1011)
        return

    @pc.on("icecandidate")
    async def on_icecandidate(event):
        if event.candidate:
            try:
                await websocket.send_json({"candidate": event.candidate.__dict__})
            except Exception as e:
                print(f"Error sending ICE candidate: {e}")

    try:
        while True:
            try:
                data = await websocket.receive_json()

                if isinstance(data, dict) and data.get("type") == "bye":
                    print(f"🔌 Received bye for camera {camera_id}, closing signaling loop")
                    break

                if data.get("sdp") and data.get("type") == "offer":
                    try:
                        await pc.setRemoteDescription(
                            RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                        )
                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)
                        await websocket.send_json({
                            "sdp": pc.localDescription.sdp,
                            "type": pc.localDescription.type
                        })
                        print(f"🎥 Answer enviado para cámara {camera_id}")
                    except Exception as e:
                        print(f"Error handling SDP offer: {e}")

                elif data.get("candidate"):
                    cand = data["candidate"]
                    print(f"Received ICE candidate: {cand}")

                    try:
                        ice_candidate = {
                            "candidate": cand["candidate"],
                            "sdpMid": cand.get("sdpMid", "0"),
                            "sdpMLineIndex": cand.get("sdpMLineIndex", 0)
                        }
                        
                        await pc.addIceCandidate(ice_candidate)
                        print(f"✅ ICE candidate added successfully")
                        
                    except Exception as e:
                        print(f"⚠️ Could not add ICE candidate (continuing anyway): {e}")

                elif isinstance(data, str) and data.strip().lower() == "bye":
                    break

            except json.JSONDecodeError:
                print(f"Invalid JSON received from client for camera {camera_id}")
                continue

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for camera {camera_id}")
    except Exception as e:
        print(f"WebSocket error for camera {camera_id}: {e}")
    finally:
        print(f"🔌 Closing video track for camera {camera_id} finally")

        try:
            print(f"🔌 Stopping video track for camera {camera_id}")
            await video_track.stop(camera_streams, camera_registry)
        except Exception as e:
            print(f"Error stopping video track: {e}")

        try:
            print(f"🔌 Closing RTCPeerConnection for camera {camera_id}")
            await pc.close()
        except Exception as e:
            print(f"Error closing RTCPeerConnection: {e}")
