import websockets
import json

async def stop_gateway_stream_ws(camera_id: int, gateway_ws_url: str):
    try:
        async with websockets.connect(gateway_ws_url) as ws:
            await ws.send(json.dumps({"action": "stop_stream", "camera_id": camera_id}))
            response = await ws.recv()
            print(f"Gateway WS response: {response}")
    except Exception as e:
        print(f"🚨 Failed to stop stream via WS for camera {camera_id}: {e}")
