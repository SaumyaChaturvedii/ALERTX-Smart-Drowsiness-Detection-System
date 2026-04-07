import cv2
import threading
import time
from collections import deque
import numpy as np

class ThreadedCamera:
    """Threaded camera capturing frames to maintain perfect FPS."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.cap = cv2.VideoCapture(cfg.CAM_INDEX)
        
        # Configure best resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, cfg.CAMERA_FPS)
        try:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        except Exception:
            pass

        self.actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or cfg.CAMERA_WIDTH)
        self.actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or cfg.CAMERA_HEIGHT)
        self.actual_fps = self.cap.get(cv2.CAP_PROP_FPS) or cfg.CAMERA_FPS

        self._frame = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # Ring buffer holds the last 5 seconds of footage
        self.buffer_seconds = 5
        self.frame_buffer = deque(maxlen=int(self.actual_fps * self.buffer_seconds))

        if self.cap.isOpened():
            self._thread = threading.Thread(target=self._update_loop, daemon=True)
            self._thread.start()

    def _update_loop(self):
        while not self._stop_event.is_set():
            ok, frame = self.cap.read()
            if ok and frame is not None:
                frame = cv2.flip(frame, 1)
                with self._lock:
                    self._frame = frame
                    self.frame_buffer.append(frame.copy())
            else:
                time.sleep(0.01)

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def get_buffer(self):
        with self._lock:
            return list(self.frame_buffer)

    def close(self):
        self._stop_event.set()
        if hasattr(self, '_thread'):
            self._thread.join(timeout=1.0)
        self.cap.release()
