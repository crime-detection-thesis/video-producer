import asyncio
from app.shared_state import signaling_websockets, camera_viewers

async def _is_websocket_valid(conn_state) -> bool:
    if not conn_state or not hasattr(conn_state, 'ws') or not conn_state.ws:
        return False
    ws = conn_state.ws
    if ws.client_state.value > 2:
        return False
    try:
        await asyncio.wait_for(ws.send_json({"event": "ping"}), timeout=1.0)
        return True
    except (asyncio.TimeoutError, RuntimeError, ConnectionError, Exception) as e:
        print(f"[DEBUG] WebSocket validation failed: {e}")
        return False

async def _send_to_websocket(conn_state, camera_id: int) -> bool:
    if not hasattr(conn_state, 'ws') or not conn_state.ws:
        return False
    try:
        await conn_state.ws.send_json({
            "event": "detection",
            "camera_id": camera_id
        })
        return True
    except Exception as e:
        print(f"[DEBUG] Failed to send to WebSocket: {e}")
        return False

async def send_detection_event(camera_id: int) -> bool:
    if not isinstance(camera_id, int):
        print(f"[ERROR] Invalid camera_id type: {type(camera_id)}. Expected int.")
        return False
    
    if camera_viewers.get(camera_id, 0) <= 0:
        if camera_id in signaling_websockets:
            del signaling_websockets[camera_id]
        print(f"[WARNING] No active viewers for camera {camera_id}")
        return False
    
    websockets = signaling_websockets.get(camera_id, set())
    if not websockets:
        print(f"[WARNING] No WebSockets found for camera {camera_id}")
        return False
    
    websockets_copy = websockets.copy()
    success = False
    stale_websockets = set()
    
    for ws in websockets_copy:
        if await _is_websocket_valid(ws):
            if await _send_to_websocket(ws, camera_id):
                success = True
            else:
                stale_websockets.add(ws)
        else:
            stale_websockets.add(ws)
    
    if stale_websockets and camera_id in signaling_websockets:
        signaling_websockets[camera_id] -= stale_websockets
        if not signaling_websockets[camera_id]:
            del signaling_websockets[camera_id]
            if camera_id in camera_viewers:
                del camera_viewers[camera_id]
        else:
            camera_viewers[camera_id] = len(signaling_websockets[camera_id])
    
    if success:
        print(f"[INFO] Detection event sent for camera {camera_id} to {len(websockets_copy) - len(stale_websockets)} clients")
    else:
        print(f"[WARNING] Failed to send detection event for camera {camera_id} to any client")
    
    return success