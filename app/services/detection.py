import cv2
import numpy as np
from typing import Any
from app.inference.handler import InferenceClient

class DetectionService:
    def __init__(self, inference_url: str, camera_id: int):
        self.client = InferenceClient(inference_url, camera_id)

    async def detect(self, frame: np.ndarray) -> dict[str, Any]:
        result = await self.client.send_frame(frame)
        return result or {"detections": [], "max_conf": 0.0}

    @staticmethod
    def draw_boxes(frame: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
        frame_copy = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = map(int, det["box"])
            label = det.get("label", "object")
            confidence = det.get("confidence", 0.0)

            color = (0, 255, 0)
            cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 2)
            text = f"{label}: {confidence:.2f}"
            cv2.putText(frame_copy, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 8)

        return frame_copy
