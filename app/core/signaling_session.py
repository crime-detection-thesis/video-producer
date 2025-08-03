import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.signaling import candidate_from_sdp
from fastapi import WebSocket, WebSocketDisconnect

from app.services.webrtc_track import CameraVideoTrack
from app.shared_state import signaling_websockets, camera_viewers
from app.core.config import config, pcs
from app.core.connection_state import ConnectionState
from app.utils.gateway_control import stop_gateway_stream

class WebRTCSignalingSession:
    def __init__(self, ws: WebSocket, camera_id: int):
        self.ws = ws
        self.camera_id = camera_id
        self.conn_state = None
        self.user_id = None
        self.pc = None

    async def run(self):
        print(f"🔌 Accepting WebSocket signaling for camera {self.camera_id}")
        await self.ws.accept()
        self.conn_state = self._init_connection()
        try:
            await self._exchange_offer_answer()
            await self._handle_signaling_messages()
        except asyncio.TimeoutError:
            print(f"⌛ Timeout waiting for offer from camera {self.camera_id}")
        except WebSocketDisconnect:
            print(f"❌ WebSocket disconnected for camera {self.camera_id}")
        except Exception as e:
            print(f"🚨 Error in WebRTC signaling for camera {self.camera_id}: {e}")
        finally:
            await self._final_cleanup()

    def _init_connection(self):
        if self.camera_id not in signaling_websockets:
            signaling_websockets[self.camera_id] = set()
        conn_state = ConnectionState(self.camera_id, self.ws)
        signaling_websockets[self.camera_id].add(conn_state)
        camera_viewers[self.camera_id] = len(signaling_websockets[self.camera_id])
        print(f"✅ WebSocket connected for camera {self.camera_id}. Total viewers: {camera_viewers[self.camera_id]}")
        return conn_state

    async def _exchange_offer_answer(self):
        init = await asyncio.wait_for(self.ws.receive_json(), timeout=30.0)
        sdp, typ = init.get("sdp"), init.get("type")
        self.user_id = init.get("user_id", str(self.camera_id))
        self.conn_state.user_id = self.user_id

        if not sdp or typ != "offer":
            print(f"❌ Invalid offer from camera {self.camera_id}")
            await self.ws.close(code=4002)
            raise Exception("Invalid offer")

        print(f"📡 Received WebRTC offer from camera {self.camera_id}, user {self.user_id}")
        self.pc = RTCPeerConnection(configuration=config)
        pcs.add(self.pc)
        self.conn_state.pc = self.pc
        self.pc.addTrack(CameraVideoTrack(self.camera_id, self.user_id))
        print(f"👤 User {self.user_id} setting up WebRTC for camera {self.camera_id}")
        self._register_pc_events()

        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        await self.ws.send_json({"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type})

    def _register_pc_events(self):
        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"WebRTC connection state for camera {self.camera_id}, user {self.user_id}: {self.pc.connectionState}")
            if self.pc.connectionState in ("failed", "closed"):
                self.conn_state.is_connected = False
                await self._cleanup_connection()

        @self.pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate and self.conn_state.is_connected:
                try:
                    await self.ws.send_json({"candidate": event.candidate.__dict__})
                except Exception as e:
                    print(f"⚠️ Error sending ICE candidate: {e}")
                    self.conn_state.is_connected = False
                    await self._cleanup_connection()

    async def _handle_signaling_messages(self):
        while self.conn_state.is_connected:
            try:
                data = await self.ws.receive_json()
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "bye":
                    print(f"👋 Received 'bye' from user {self.user_id} for camera {self.camera_id}")
                    break
                elif data.get("candidate"):
                    await self._add_ice_candidate(data["candidate"])
            except WebSocketDisconnect:
                print(f"❌ WebSocket disconnected for camera {self.camera_id}, user {self.user_id}")
                break
            except asyncio.CancelledError:
                print(f"ℹ️ WebSocket task cancelled for camera {self.camera_id}, user {self.user_id}")
                break
            except Exception as e:
                print(f"⚠️ Error in WebSocket message handling for camera {self.camera_id}, user {self.user_id}: {e}")
                break

    async def _add_ice_candidate(self, candidate_info):
        sdp = candidate_info.get("candidate")
        sdp_mid = candidate_info.get("sdpMid")
        sdp_mline_index = candidate_info.get("sdpMLineIndex")
        if sdp and sdp_mid is not None and sdp_mline_index is not None:
            try:
                candidate = candidate_from_sdp(sdp)
                candidate.sdpMid = sdp_mid
                candidate.sdpMLineIndex = sdp_mline_index
                await self.pc.addIceCandidate(candidate)
            except Exception as e:
                print(f"⚠️ Error adding ICE candidate: {e}")

    async def _cleanup_connection(self):
        pc = getattr(self.conn_state, 'pc', None)
        if pc and pc.connectionState != "closed":
            if pc in pcs:
                pcs.remove(pc)
            try:
                await pc.close()
            except Exception as e:
                print(f"⚠️ Error closing peer connection: {e}")

        if self.camera_id in signaling_websockets and self.conn_state in signaling_websockets[self.camera_id]:
            signaling_websockets[self.camera_id].remove(self.conn_state)
            if not signaling_websockets[self.camera_id]:
                del signaling_websockets[self.camera_id]
                if self.camera_id in camera_viewers:
                    del camera_viewers[self.camera_id]
                print(f"🧹 Removed last WebSocket for camera {self.camera_id}")
                try:
                    print(f"🛑 No more viewers for camera {self.camera_id}, stopping gateway stream...")
                    await stop_gateway_stream(self.camera_id)
                except Exception as e:
                    print(f"⚠️ Error stopping gateway stream for camera {self.camera_id}: {e}")
            else:
                camera_viewers[self.camera_id] = len(signaling_websockets[self.camera_id])
                print(f"🧹 Removed WebSocket for camera {self.camera_id}. Remaining viewers: {camera_viewers[self.camera_id]}")

    async def _final_cleanup(self):
        if hasattr(self.conn_state, 'pc') and self.conn_state.pc:
            await self._cleanup_connection()
        else:
            if self.camera_id in signaling_websockets and self.conn_state in signaling_websockets[self.camera_id]:
                signaling_websockets[self.camera_id].remove(self.conn_state)
                if not signaling_websockets[self.camera_id]:
                    del signaling_websockets[self.camera_id]
                    if self.camera_id in camera_viewers:
                        del camera_viewers[self.camera_id]
                else:
                    camera_viewers[self.camera_id] = len(signaling_websockets[self.camera_id])
        
        if hasattr(self.ws, 'close') and self.ws.client_state.value <= 2:
            try:
                await self.ws.close()
            except Exception as e:
                print(f"⚠️ Error closing WebSocket: {e}")
