import cv2
import numpy as np
import websockets
import asyncio
import json

class InferenceClient:
    def __init__(self, inference_url: str, user_id: int):
        self.inference_url = inference_url
        self.user_id = user_id
        self.websocket = None

    async def connect(self):
        try:
            print('🔌 Connecting to inference server...')
            self.websocket = await websockets.connect(f'{self.inference_url}/{self.user_id}')
            init_msg = json.dumps({"user_id": self.user_id})
            await self.websocket.send(init_msg)
        except Exception as e:
            print(f"⚠️ Failed to connect to inference server: {e}")
            self.websocket = None

    async def send_frame(self, frame: np.ndarray):
        for attempt in range(2):  # One retry
            if not self.websocket:
                await self.connect()
                if not self.websocket:
                    return None

            try:
                _, frame_encoded = cv2.imencode('.jpg', frame)
                frame_bytes = frame_encoded.tobytes()
                await self.websocket.send(frame_bytes)

                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                return json.loads(response)

            except asyncio.TimeoutError:
                print("⚠️ Inference server response timed out.")
            except Exception as e:
                print(f"⚠️ Error communicating with inference server: {e}")

            await self.close()
        return None

    async def close(self):
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None
