import time

class FatigueScorer:
    """
    Dynamic weighted scoring system returning 0 to 100.
    0 = Perfectly alert
    100 = Extremely drowsy / dangerous sleep
    """
    def __init__(self, cfg):
        self.cfg = cfg
        self.score = 0.0
        self.last_update = time.time()
        
        self._eyes_closed_since = None
        
    def evaluate(self, trackers: dict, face_tracked: bool) -> dict:
        now = time.time()
        
        if not face_tracked:
            self.score = min(100.0, self.score + (now - self.last_update) * 10)
            self.last_update = now
            return self._finalize_score("FACE_LOST")

        ear = trackers['ear']
        ear_thresh = trackers['ear_threshold']
        mar = trackers['mar']
        mar_thresh = self.cfg.MAR_THRESHOLD
        
        perclos_val = trackers['perclos']
        bpm = trackers['bpm']
        is_nodding = trackers['is_nodding']
        
        is_eyes_closed = ear < ear_thresh
        
        # 1. Base Score Decay
        # Naturally decays back to 0 when person is alert
        delta_t = now - self.last_update
        self.last_update = now
        
        if not is_eyes_closed:
            self.score = max(0.0, self.score - (delta_t * 15)) # recovers fast when eyes open
            self._eyes_closed_since = None
        else:
            if self._eyes_closed_since is None:
                self._eyes_closed_since = now
            
            closed_duration = now - self._eyes_closed_since
            # Exponential penalty for continuous eye closure
            closure_penalty = (closed_duration ** 2) * 20
            self.score += closure_penalty * delta_t

        # 2. PERCLOS Penalty
        # PERCLOS > 0.15 adds sustained fatigue score
        if perclos_val > 0.15:
            self.score += ((perclos_val - 0.15) * 100) * delta_t

        # 3. Yawn Penalty
        if mar > mar_thresh:
            self.score += 5 * delta_t
            
        # 4. Nod Penalty (Instant jump)
        if is_nodding:
            self.score = max(self.score, 60.0) # instantly jumping to warning range
            
        # 5. Blink Rate Penalty
        if bpm > 25: 
            self.score += 2 * delta_t
        elif bpm > 0 and bpm < 8:
            self.score += 3 * delta_t
            
        return self._finalize_score("TRACKING")

    def _finalize_score(self, tracking_state: str):
        self.score = max(0.0, min(100.0, self.score))
        
        state = "SAFE"
        level_flag = "N"
        
        if self.score >= self.cfg.ALERT_LEVELS["SLEEP"]:
            state = "SLEEP"
            level_flag = "D3"
        elif self.score >= self.cfg.ALERT_LEVELS["CRITICAL"]:
            state = "CRITICAL"
            level_flag = "D2"
        elif self.score >= self.cfg.ALERT_LEVELS["WARNING"]:
            state = "WARNING"
            level_flag = "D1"
            
        return {
            "score": self.score,
            "state": state,
            "level_flag": level_flag,
            "tracking_state": tracking_state,
            "eyes_closed_dur": 0 if self._eyes_closed_since is None else time.time() - self._eyes_closed_since
        }
