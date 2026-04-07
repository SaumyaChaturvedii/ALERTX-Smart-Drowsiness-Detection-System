import os
import tempfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def ensure_writable_dir(preferred: str, fallback_root: str = None) -> str:
    fallback_root = fallback_root or os.path.join(tempfile.gettempdir(), "dds_v3")
    for path in (preferred, os.path.join(fallback_root, os.path.basename(preferred))):
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, ".write_test")
            with open(test_file, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(test_file)
            return path
        except OSError:
            continue
    raise OSError(f"Could not create writable directory for {preferred}")

class Config:
    def __init__(self):
        # Hardware
        self.SERIAL_PORT = 'COM5'
        self.BAUD_RATE = 9600
        self.USE_ARDUINO = True

        # Camera
        self.CAM_INDEX = 0
        self.CAMERA_WIDTH = 1920
        self.CAMERA_HEIGHT = 1080
        self.CAMERA_FPS = 30
        self.PROCESS_EVERY = 2
        self.PROCESS_WIDTH = 640

        # Features
        self.MUTE = False
        self.SAVE_VIDEO = True
        
        # Paths
        self.MODEL_DIR = ensure_writable_dir(os.path.join(BASE_DIR, "models"))
        self.FACE_LANDMARKER_MODEL = os.path.join(self.MODEL_DIR, "face_landmarker.task")
        self.LOG_DIR = ensure_writable_dir(os.path.join(BASE_DIR, "drowsiness_logs"))
        self.VIDEO_DIR = ensure_writable_dir(os.path.join(BASE_DIR, "alert_clips"))
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.LOG_FILE = os.path.join(self.LOG_DIR, f"session_{ts}.log")
        self.REPORT_FILE = os.path.join(self.LOG_DIR, f"report_{ts}.json")

        # Thresholds
        self.EAR_THRESHOLD = 0.25
        self.MAR_THRESHOLD = 0.50
        self.EAR_DILATION_FACTOR = 0.78
        self.NOD_THRESHOLD = 0.08
        self.PERCLOS_WINDOW_SEC = 60
        self.BLINK_RATE_WINDOW_SEC = 60

        # Scoring System
        self.MAX_SCORE = 100
        
        # Alert Ranges
        self.ALERT_LEVELS = {
            "SAFE": 20,           # 0-20
            "WARNING": 50,        # 21-50 (D1)
            "CRITICAL": 80,       # 51-80 (D2)
            "SLEEP": 100          # 81-100 (D3)
        }

cfg = Config()
