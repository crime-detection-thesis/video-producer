from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer
)
from aiortc.contrib.signaling import candidate_from_sdp

from fastapi import WebSocket
from app.services.webrtc_track import CameraVideoTrack

ice_servers = [
    RTCIceServer(urls="stun:stun.l.google.com:19302"),
    RTCIceServer(
        urls="turn:openrelay.metered.ca:80",
        username="openrelayproject",
        credential="openrelayproject"
    ),
]
config = RTCConfiguration(iceServers=ice_servers)

pcs = set()

async def handle_signaling(ws: WebSocket, camera_id: int):
    print(f"🔌 Accepting WebSocket signaling for camera {camera_id}")
    await ws.accept()

    pc = None  # 🛠️ Prevent UnboundLocalError if early exit

    try:
        init = await ws.receive_json()
        sdp = init.get("sdp")
        typ = init.get("type")

        if not sdp or typ != "offer":
            await ws.close(code=4002)
            return

        pc = RTCPeerConnection(configuration=config)
        pcs.add(pc)

        pc.addTrack(CameraVideoTrack(camera_id))

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await ws.send_json({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })

        @pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate:
                await ws.send_json({"candidate": event.candidate.__dict__})

        while True:
            data = await ws.receive_json()
            if isinstance(data, dict):
                if data.get("type") == "bye":
                    break
                elif data.get("candidate"):
                    # # ✅ Fix: convert to RTCIceCandidate
                    # candidate = RTCIceCandidate(**data["candidate"])
                    # await pc.addIceCandidate(candidate)

                    candidate_info = data["candidate"]
                    sdp = candidate_info.get("candidate")
                    sdp_mid = candidate_info.get("sdpMid")
                    sdp_mline_index = candidate_info.get("sdpMLineIndex")

                    if sdp and sdp_mid is not None and sdp_mline_index is not None:
                        candidate = candidate_from_sdp(sdp)
                        candidate.sdpMid = sdp_mid
                        candidate.sdpMLineIndex = sdp_mline_index
                        await pc.addIceCandidate(candidate)

    except Exception as e:
        print("❌ Signaling error:", e)

    finally:
        if pc:
            await pc.close()
            pcs.discard(pc)
