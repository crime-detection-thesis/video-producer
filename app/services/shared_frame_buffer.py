import threading
import numpy as np

class SharedFrameBuffer:
    def __init__(self):
        self.latest_frame = None
        self.lock = threading.Lock()
        self.finished = False

    def update_frame(self, frame: np.ndarray):
        with self.lock:
            self.latest_frame = frame

    def get_latest_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None
