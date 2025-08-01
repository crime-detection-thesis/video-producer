import asyncio

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.signaling import candidate_from_sdp
from fastapi import WebSocket, WebSocketDisconnect

from app.services.webrtc_track import CameraVideoTrack
from app.shared_state import signaling_websockets
from app.core.config import config, pcs

async def handle_signaling(ws: WebSocket, camera_id: int):
    print(f"🔌 Accepting WebSocket signaling for camera {camera_id}")
    await ws.accept()
    
    signaling_websockets[camera_id] = ws
    pc = None
    
    is_connected = True
    print(f"✅ WebSocket connected for camera {camera_id}")

    try:
        init = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
        sdp = init.get("sdp")
        typ = init.get("type")
        user_id = init.get("user_id", str(camera_id))

        if not sdp or typ != "offer":
            print(f"❌ Invalid offer from camera {camera_id}")
            await ws.close(code=4002)
            return
            
        print(f"📡 Received WebRTC offer from camera {camera_id}, user {user_id}")

        pc = RTCPeerConnection(configuration=config)
        pcs.add(pc)
        
        print(f"👤 User {user_id} setting up WebRTC for camera {camera_id}")
        
        pc.addTrack(CameraVideoTrack(camera_id, user_id))
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"WebRTC connection state for camera {camera_id}: {pc.connectionState}")
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                if pc in pcs:
                    pcs.remove(pc)
                if camera_id in signaling_websockets and signaling_websockets[camera_id] == ws:
                    del signaling_websockets[camera_id]
                    print(f"🧹 Cleaned up WebSocket for camera {camera_id}")
                is_connected = False

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
                    candidate_info = data["candidate"]
                    sdp = candidate_info.get("candidate")
                    sdp_mid = candidate_info.get("sdpMid")
                    sdp_mline_index = candidate_info.get("sdpMLineIndex")

                    if sdp and sdp_mid is not None and sdp_mline_index is not None:
                        candidate = candidate_from_sdp(sdp)
                        candidate.sdpMid = sdp_mid
                        candidate.sdpMLineIndex = sdp_mline_index
                        await pc.addIceCandidate(candidate)

    except asyncio.TimeoutError:
        print(f"⌛ Timeout waiting for offer from camera {camera_id}")
    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected for camera {camera_id}")
    except Exception as e:
        print(f"🚨 Error in WebRTC signaling for camera {camera_id}: {e}")
    finally:
        if camera_id in signaling_websockets and signaling_websockets[camera_id] == ws:
            del signaling_websockets[camera_id]
            print(f"🧹 Cleaned up WebSocket for camera {camera_id}")
            
        if pc and pc.connectionState != "closed":
            try:
                pcs.discard(pc)
                await pc.close()
                print(f"🔌 Closed peer connection for camera {camera_id}")
            except Exception as e:
                print(f"⚠️ Error closing peer connection for camera {camera_id}: {e}")
