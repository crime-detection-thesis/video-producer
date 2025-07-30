import httpx
from app.config import GATEWAY_URL

async def stop_gateway_stream(camera_id: int):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GATEWAY_URL}/stop-camera",
                json={"camera_id": camera_id}
            )
            if response.status_code == 200:
                print(f"✅ Gateway stream stopped for camera {camera_id}")
            else:
                print(f"⚠️ Gateway refused to stop stream (code {response.status_code})")
    except Exception as e:
        print(f"🚨 Failed to contact gateway for camera {camera_id}: {e}")
