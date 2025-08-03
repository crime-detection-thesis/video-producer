import asyncio

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.signaling import candidate_from_sdp
from fastapi import WebSocket, WebSocketDisconnect

from app.services.webrtc_track import CameraVideoTrack
from app.shared_state import signaling_websockets, camera_viewers
from app.core.config import config, pcs
from app.utils.gateway_control import stop_gateway_stream


class ConnectionState:
    def __init__(self, camera_id: int, ws: WebSocket):
        self.camera_id = camera_id
        self.ws = ws
        self.pc = None
        self.is_connected = True
        self.user_id = None

async def handle_signaling(ws: WebSocket, camera_id: int):
    print(f"🔌 Accepting WebSocket signaling for camera {camera_id}")
    await ws.accept()
    
    if camera_id not in signaling_websockets:
        signaling_websockets[camera_id] = set()
    
    conn_state = ConnectionState(camera_id, ws)
    
    signaling_websockets[camera_id].add(conn_state)
    
    camera_viewers[camera_id] = len(signaling_websockets[camera_id])
    print(f"✅ WebSocket connected for camera {camera_id}. Total viewers: {camera_viewers[camera_id]}")

    try:
        init = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
        sdp = init.get("sdp")
        typ = init.get("type")
        user_id = init.get("user_id", str(camera_id))
        conn_state.user_id = user_id

        if not sdp or typ != "offer":
            print(f"❌ Invalid offer from camera {camera_id}")
            await ws.close(code=4002)
            return
            
        print(f"📡 Received WebRTC offer from camera {camera_id}, user {user_id}")

        conn_state.pc = RTCPeerConnection(configuration=config)
        pc = conn_state.pc
        pcs.add(pc)
        
        print(f"👤 User {user_id} setting up WebRTC for camera {camera_id}")
        
        pc.addTrack(CameraVideoTrack(camera_id, user_id))
        
        async def cleanup_connection():
            if pc and pc.connectionState != "closed":
                if pc in pcs:
                    pcs.remove(pc)
                try:
                    await pc.close()
                except Exception as e:
                    print(f"⚠️ Error closing peer connection: {e}")
            
            if camera_id in signaling_websockets and conn_state in signaling_websockets[camera_id]:
                signaling_websockets[camera_id].remove(conn_state)
                if not signaling_websockets[camera_id]:
                    del signaling_websockets[camera_id]
                    if camera_id in camera_viewers:
                        del camera_viewers[camera_id]
                    print(f"🧹 Removed last WebSocket for camera {camera_id}")
                    try:
                        print(f"🛑 No more viewers for camera {camera_id}, stopping gateway stream...")
                        await stop_gateway_stream(camera_id)
                    except Exception as e:
                        print(f"⚠️ Error stopping gateway stream for camera {camera_id}: {e}")
                else:
                    camera_viewers[camera_id] = len(signaling_websockets[camera_id])
                    print(f"🧹 Removed WebSocket for camera {camera_id}. Remaining viewers: {camera_viewers[camera_id]}")
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"WebRTC connection state for camera {camera_id}, user {user_id}: {pc.connectionState}")
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                conn_state.is_connected = False
                await cleanup_connection()

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await ws.send_json({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })

        @pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate and conn_state.is_connected:
                try:
                    await ws.send_json({"candidate": event.candidate.__dict__})
                except Exception as e:
                    print(f"⚠️ Error sending ICE candidate: {e}")
                    conn_state.is_connected = False
                    await cleanup_connection()

        while conn_state.is_connected:
            try:
                data = await ws.receive_json()
                if not isinstance(data, dict):
                    continue
                    
                if data.get("type") == "bye":
                    print(f"👋 Received 'bye' from user {user_id} for camera {camera_id}")
                    break
                    
                elif data.get("candidate"):
                    candidate_info = data["candidate"]
                    sdp = candidate_info.get("candidate")
                    sdp_mid = candidate_info.get("sdpMid")
                    sdp_mline_index = candidate_info.get("sdpMLineIndex")

                    if sdp and sdp_mid is not None and sdp_mline_index is not None:
                        try:
                            candidate = candidate_from_sdp(sdp)
                            candidate.sdpMid = sdp_mid
                            candidate.sdpMLineIndex = sdp_mline_index
                            await pc.addIceCandidate(candidate)
                        except Exception as e:
                            print(f"⚠️ Error adding ICE candidate: {e}")
                            
            except WebSocketDisconnect:
                print(f"❌ WebSocket disconnected for camera {camera_id}, user {user_id}")
                break
            except asyncio.CancelledError:
                print(f"ℹ️ WebSocket task cancelled for camera {camera_id}, user {user_id}")
                break
            except Exception as e:
                print(f"⚠️ Error in WebSocket message handling for camera {camera_id}, user {user_id}: {e}")
                break

    except asyncio.TimeoutError:
        print(f"⌛ Timeout waiting for offer from camera {camera_id}")
    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected for camera {camera_id}")
    except Exception as e:
        print(f"🚨 Error in WebRTC signaling for camera {camera_id}: {e}")
    finally:
        if hasattr(conn_state, 'pc') and conn_state.pc:
            await cleanup_connection()
        else:
            if camera_id in signaling_websockets and conn_state in signaling_websockets[camera_id]:
                signaling_websockets[camera_id].remove(conn_state)
                if not signaling_websockets[camera_id]:
                    del signaling_websockets[camera_id]
                    if camera_id in camera_viewers:
                        del camera_viewers[camera_id]
                else:
                    camera_viewers[camera_id] = len(signaling_websockets[camera_id])
        
        # Final cleanup
        if hasattr(ws, 'close') and ws.client_state.value <= 2:  # 2 = WebSocketState.CONNECTED
            try:
                await ws.close()
            except Exception as e:
                print(f"⚠️ Error closing WebSocket: {e}")
