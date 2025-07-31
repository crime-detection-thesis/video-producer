import numpy as np
import threading
from typing import Optional, Tuple

class SharedFrameBuffer:
    def __init__(self, shape: Tuple[int, int, int] = (1080, 1920, 3), dtype=np.uint8):
        self._buffer = np.zeros(shape, dtype=dtype)
        self._has_frame = False
        self._lock = threading.RLock()
        self._frame_shape = shape
        self._dtype = dtype

    def update_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            if frame.shape != self._frame_shape or frame.dtype != self._dtype:
                self._buffer = np.empty_like(frame)
                self._frame_shape = frame.shape
                self._dtype = frame.dtype
            np.copyto(self._buffer, frame)
            self._has_frame = True

    def get_latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            if not self._has_frame:
                return None
            return self._buffer.copy()
