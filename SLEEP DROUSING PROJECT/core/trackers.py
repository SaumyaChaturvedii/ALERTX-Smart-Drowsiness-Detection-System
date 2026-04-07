import time
from collections import deque
import numpy as np

# Landmark Indices from MediaPipe FaceMesh
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
MOUTH_TOP = 13
MOUTH_BOTTOM = 14
MOUTH_OUTER_LEFT = 78
MOUTH_OUTER_RIGHT = 308
NOSE_TIP = 1
FOREHEAD_TOP = 10
CHIN_BOTTOM = 152

class FacialMetricsTracker:
    def __init__(self, ear_smoothing=3, mar_smoothing=5):
        self.ear_window = deque(maxlen=ear_smoothing)
        self.mar_window = deque(maxlen=mar_smoothing)
        self.open_eye_samples = deque(maxlen=120)
        
        self.ear = 0.0
        self.mar = 0.0
        self.nose_y = 0.0
        self.dynamic_ear_threshold = 0.25

    def get_ear(self, landmarks, eye_indices, w, h):
        pts = [np.array([landmarks[idx].x * w, landmarks[idx].y * h]) for idx in eye_indices]
        v1 = np.linalg.norm(pts[1] - pts[5])
        v2 = np.linalg.norm(pts[2] - pts[4])
        h_d = np.linalg.norm(pts[0] - pts[3])
        return (v1 + v2) / (2.0 * h_d + 1e-6)

    def update(self, landmarks, w, h):
        l_ear = self.get_ear(landmarks, LEFT_EYE, w, h)
        r_ear = self.get_ear(landmarks, RIGHT_EYE, w, h)
        raw_ear = (l_ear + r_ear) / 2.0
        
        # Simple MAR
        mt = np.array([landmarks[MOUTH_TOP].x * w, landmarks[MOUTH_TOP].y * h])
        mb = np.array([landmarks[MOUTH_BOTTOM].x * w, landmarks[MOUTH_BOTTOM].y * h])
        ml = np.array([landmarks[MOUTH_OUTER_LEFT].x * w, landmarks[MOUTH_OUTER_LEFT].y * h])
        mr = np.array([landmarks[MOUTH_OUTER_RIGHT].x * w, landmarks[MOUTH_OUTER_RIGHT].y * h])
        v_gap = np.linalg.norm(mt - mb)
        h_gap = np.linalg.norm(ml - mr)
        raw_mar = v_gap / (h_gap + 1e-6)

        self.ear_window.append(raw_ear)
        self.mar_window.append(raw_mar)
        self.ear = float(np.median(self.ear_window))
        self.mar = float(np.mean(self.mar_window))
        
        # Nose Y for Nod
        face_top = landmarks[FOREHEAD_TOP].y * h
        face_bottom = landmarks[CHIN_BOTTOM].y * h
        face_h = abs(face_bottom - face_top) + 1e-6
        nose_y = landmarks[NOSE_TIP].y * h
        self.nose_y = (nose_y - face_top) / face_h

        # Update dynamic EAR threshold
        if self.ear > 0.19:
            self.open_eye_samples.append(self.ear)
        if len(self.open_eye_samples) >= 12:
            self.dynamic_ear_threshold = float(np.median(self.open_eye_samples)) * 0.78
        return self.ear, self.mar, self.nose_y

class BlinkTracker:
    def __init__(self, window_sec=60):
        self._window = window_sec
        self._timestamps = deque()
        self._is_closed = False
        self._closed_since = 0.0

    def update(self, eyes_closed: bool, now: float):
        if eyes_closed:
            if not self._is_closed:
                self._closed_since = now
            self._is_closed = True
        elif self._is_closed:
            duration = now - self._closed_since
            if 0.06 <= duration <= 0.45:
                self._timestamps.append(now)
            self._is_closed = False

        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def blinks_per_min(self):
        return len(self._timestamps)

class PerclosTracker:
    def __init__(self, window_sec=60, fps=15):
        self._q = deque(maxlen=window_sec * fps)
        self._closed_count = 0

    def update(self, eyes_closed: bool):
        val = 1 if eyes_closed else 0
        if len(self._q) == self._q.maxlen:
            self._closed_count -= self._q[0]
        self._q.append(val)
        self._closed_count += val

    @property
    def value(self) -> float:
        if not self._q: return 0.0
        eff = max(len(self._q), int(self._q.maxlen * 0.25))
        return self._closed_count / eff

class NodTracker:
    def __init__(self, threshold=0.08, history=15):
        self.threshold = threshold
        self._q = deque(maxlen=history)
        self.nods_detected = 0
        self.is_nodding = False

    def update(self, nose_y_norm: float) -> bool:
        self._q.append(nose_y_norm)
        if len(self._q) < 5: return False
        baseline = np.mean(list(self._q)[:5])
        nod = (nose_y_norm - baseline) > self.threshold
        
        if nod and not self.is_nodding:
            self.nods_detected += 1
        
        if self.is_nodding and not nod and (nose_y_norm - baseline) < (self.threshold * 0.3):
            self.is_nodding = False
        elif nod:
            self.is_nodding = True
            
        return nod
