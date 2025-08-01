import asyncio
import time

from app.shared_state import signaling_websockets

async def send_detection_event(camera_id: int):
    if not isinstance(camera_id, int):
        print(f"[ERROR] Invalid camera_id type: {type(camera_id)}. Expected int.")
        return False
        
    if camera_id not in signaling_websockets:
        print(f"[WARNING] No active signaling WebSocket for camera {camera_id}")
        return False
    
    ws = signaling_websockets.get(camera_id)
    if not ws or ws.client_state.value > 2:  # 2 = WebSocketState.CONNECTED
        print(f"[WARNING] WebSocket for camera {camera_id} is not in connected state")
        if camera_id in signaling_websockets:
            del signaling_websockets[camera_id]
        return False
    
    try:
        try:
            await asyncio.wait_for(ws.send_json({
                "event": "ping"
            }), timeout=1.0)
        except (asyncio.TimeoutError, RuntimeError) as e:
            print(f"[WARNING] WebSocket ping failed for camera {camera_id}: {e}")
            if camera_id in signaling_websockets:
                del signaling_websockets[camera_id]
            return False
            
        await ws.send_json({
            "event": "detection",
            "camera_id": camera_id,
            "timestamp": int(time.time() * 1000)
        })
        print(f"[INFO] Detection event sent for camera {camera_id}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to send detection event for camera {camera_id}: {e}")
        if camera_id in signaling_websockets:
            del signaling_websockets[camera_id]
        return False