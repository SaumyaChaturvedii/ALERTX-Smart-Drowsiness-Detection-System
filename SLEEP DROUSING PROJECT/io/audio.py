import threading
import time
import numpy as np
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

class AudioManager:
    def __init__(self, cfg):
        self.mute = cfg.MUTE
        self._playing = False
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.level = "N"

    def _beep_once(self):
        if not HAS_WINSOUND:
            print('\a', end='', flush=True)
            time.sleep(0.5)
            return

        try:
            if self.level == "D3":
                winsound.Beep(2500, 300) # Fast critical
                time.sleep(0.1)
            elif self.level == "D2":
                winsound.Beep(1800, 400) # Medium warning
                time.sleep(0.3)
            elif self.level == "D1":
                winsound.Beep(1200, 200) # Light chime
                time.sleep(0.8)
        except Exception:
            time.sleep(0.5)

    def _loop(self):
        while not self._stop_event.is_set():
            if self.level != "N":
                self._beep_once()
            else:
                time.sleep(0.1)

    def set_level(self, level: str):
        with self._lock:
            self.level = level

    def start(self):
        if self.mute: return
        with self._lock:
            if not self._playing:
                self._playing = True
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

    def stop(self):
        with self._lock:
            self.level = "N"
            if self._playing:
                self._playing = False
                self._stop_event.set()
