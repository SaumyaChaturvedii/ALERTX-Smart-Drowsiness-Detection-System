
"""
╔══════════════════════════════════════════════════════════════╗
║         DRIVER DROWSINESS DETECTION SYSTEM  v2.0             ║
║         Author     : B.Tech CSE AI & ML                      ║
║         Tech Stack : Python + OpenCV + MediaPipe + Arduino   ║
║         Features   : EAR · MAR · PERCLOS · Blink Rate        ║
║                      Head-Nod · Live Graph · Auto-Screenshot ║
╚══════════════════════════════════════════════════════════════╝


"""

# ──────────────────────────────────────────────
#  IMPORTS  —  graceful fallback for optional libs
# ──────────────────────────────────────────────
import os
os.environ["GLOG_minloglevel"] = "2"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import mediapipe as mp
except ImportError:
    mp = None

try:
    import numpy as np
except ImportError:
    np = None

import threading
import time
import logging
import os
import sys
import json
import argparse
import tempfile
import urllib.request
import queue
from datetime import datetime
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Optional: Serial (Arduino) ──────────────────
SERIAL_AVAILABLE = False
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    pass

# ── Cross-platform Audio ─────────────────────────
# Priority: winsound (Win) → pygame → system beep
AUDIO_BACKEND = None

try:
    import winsound                          # Windows only
    AUDIO_BACKEND = 'winsound'
except ImportError:
    pass

if AUDIO_BACKEND is None:
    try:
        import pygame
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.mixer.init()
        AUDIO_BACKEND = 'pygame'
    except Exception:
        pass

if AUDIO_BACKEND is None:
    AUDIO_BACKEND = 'system'   # os.system beep fallback


def ensure_writable_dir(preferred: str, fallback_root: str = None) -> str:
    """Create a writable directory, falling back to temp if needed."""
    fallback_root = fallback_root or os.path.join(tempfile.gettempdir(), "dds_v2")
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


# ════════════════════════════════════════════════════
#  CLI ARGUMENTS — configure without editing the file
# ════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser(
        description="Driver Drowsiness Detection System v2.0",
        formatter_class=argparse.RawTextHelpFormatter
    )
    p.add_argument('--port',        default='COM5',      help="Arduino serial port (default: COM5)")
    p.add_argument('--baud',        default=9600,  type=int, help="Baud rate (default: 9600)")
    p.add_argument('--cam',         default=0,     type=int, help="Camera index (default: 0)")
    p.add_argument('--sensitivity', default=2,     type=int, choices=[1, 2, 3],
                   help="1=Low  2=Medium  3=High sensitivity")
    p.add_argument('--ear',         default=0.25,  type=float, help="Base EAR threshold (default: 0.25)")
    p.add_argument('--mar',         default=0.50,  type=float, help="Base MAR threshold (default: 0.50)")
    p.add_argument('--cooldown',    default=5,     type=int,   help="Alert cooldown seconds (default: 5)")
    p.add_argument('--no-arduino',  action='store_true',  help="Disable Arduino even if available")
    p.add_argument('--no-sound',    action='store_true',  help="Mute all alarms")
    p.add_argument('--no-save',     action='store_true',  help="Don't save alert screenshots")
    p.add_argument('--backend',     default='auto', choices=['auto', 'dshow', 'msmf', 'default'],
                   help="Preferred camera backend (default: auto)")
    p.add_argument('--width',       default=1920, type=int, help="Requested camera width (default: 1920)")
    p.add_argument('--height',      default=1080,  type=int, help="Requested camera height (default: 1080)")
    p.add_argument('--fps',         default=30,   type=int, help="Requested camera FPS (default: 30)")
    p.add_argument('--cam-scan-max', default=3, type=int,
                   help="Highest camera index to auto-scan if the requested camera fails (default: 3)")
    p.add_argument('--process-every', default=2, type=int,
                   help="Run MediaPipe every N frames (default: 2 for smoother UI on slower machines)")
    p.add_argument('--process-width', default=640, type=int,
                   help="Face-processing width after resize (default: 640)")
    return p.parse_args()


# ════════════════════════════════════════════════════
#  CONFIGURATION — derived from args + presets
# ════════════════════════════════════════════════════
class Config:
    def __init__(self, args):
        self.SERIAL_PORT         = args.port
        self.BAUD_RATE           = args.baud
        self.CAM_INDEX           = args.cam
        self.EAR_THRESHOLD       = args.ear
        self.MAR_THRESHOLD       = args.mar
        self.ALERT_COOLDOWN      = args.cooldown
        self.USE_ARDUINO         = not args.no_arduino and SERIAL_AVAILABLE
        self.MUTE                = args.no_sound
        self.SAVE_SCREENSHOTS    = not args.no_save
        self.CAMERA_BACKEND      = args.backend
        self.CAMERA_SCAN_MAX     = max(0, args.cam_scan_max)
        self.CAMERA_WIDTH        = max(640, args.width)
        self.CAMERA_HEIGHT       = max(480, args.height)
        self.CAMERA_FPS          = max(15, args.fps)
        self.PROCESS_EVERY       = max(1, args.process_every)
        self.PROCESS_WIDTH       = max(320, args.process_width)

        # Sensitivity presets
        sensitivity = args.sensitivity
        presets = {
            1: {"sleep_sec": 3.0, "yawn_sec": 1.4},
            2: {"sleep_sec": 2.0, "yawn_sec": 1.1},
            3: {"sleep_sec": 1.0, "yawn_sec": 0.9},
        }
        self.EYE_CLOSED_DROWSY_SEC = presets[sensitivity]["sleep_sec"]  # Reduced from 5.0s
        self.YAWN_MIN_SEC = presets[sensitivity]["yawn_sec"]
        self.STATE_CLEAR_SEC = 0.15  # Optimized hysteresis gap to properly tolerate noisy tracker frames without falsely clearing

        # PERCLOS window: percentage eye closure over last N seconds
        self.PERCLOS_WINDOW_SEC  = 60
        self.PERCLOS_ALERT_LEVEL = 0.35   # Increased to 35% to avoid normal blinking triggering it

        # Face lost alert after this many seconds
        self.FACE_LOST_ALERT_SEC = 5

        # Blink rate: normal 12-20 per min; >25 = fatigue sign
        self.BLINK_RATE_WINDOW_SEC = 60
        self.MIN_BLINK_SEC = 0.06
        self.MAX_BLINK_SEC = 0.45

        # Adaptive thresholds + smoothing for better real-world behavior
        self.EAR_SMOOTHING = 3
        self.MAR_SMOOTHING = 5
        self.EAR_DYNAMIC_MIN = 0.16
        self.EAR_DYNAMIC_FACTOR = 0.78
        self.MAR_DYNAMIC_MIN = 0.38
        self.MAR_DYNAMIC_OFFSET = 0.16
        self.MOUTH_OPEN_MIN_RATIO = 0.055

        # Head nod: nose drops this fraction of face height = nod
        self.NOD_THRESHOLD = 0.08
        self.CAMERA_FRAME_TIMEOUT_SEC = 3.0
        self.CAMERA_RETRY_COOLDOWN_SEC = 2.0
        self.ARDUINO_WARMUP_SEC = 2.0

        # MediaPipe Tasks face landmarker model
        self.MODEL_DIR = ensure_writable_dir(os.path.join(BASE_DIR, "models"))
        self.FACE_LANDMARKER_MODEL = os.path.join(self.MODEL_DIR, "face_landmarker.task")
        self.FACE_LANDMARKER_URL = (
            "https://storage.googleapis.com/mediapipe-models/"
            "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
        )

        # Directories
        self.LOG_DIR    = ensure_writable_dir(os.path.join(BASE_DIR, "drowsiness_logs"))
        self.SHOT_DIR   = ensure_writable_dir(os.path.join(BASE_DIR, "alert_screenshots"))

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.LOG_FILE    = os.path.join(self.LOG_DIR, f"session_{ts}.log")
        self.REPORT_FILE = os.path.join(self.LOG_DIR, f"report_{ts}.json")


# ════════════════════════════════════════════════════
#  LANDMARK INDICES (MediaPipe 468-point face mesh)
# ════════════════════════════════════════════════════
LEFT_EYE    = [362, 385, 387, 263, 373, 380]
RIGHT_EYE   = [33,  160, 158, 133, 153, 144]
MOUTH_TOP   = 13
MOUTH_BOTTOM= 14
MOUTH_LEFT  = 61
MOUTH_RIGHT = 291
MOUTH_OUTER_LEFT = 78
MOUTH_OUTER_RIGHT = 308
MOUTH_UPPER_LEFT = 81
MOUTH_LOWER_LEFT = 178
MOUTH_UPPER_RIGHT = 311
MOUTH_LOWER_RIGHT = 402
NOSE_TIP    = 1       # for nod detection
LEFT_CHEEK  = 234     # for face-height reference
RIGHT_CHEEK = 454
FOREHEAD_TOP = 10
CHIN_BOTTOM = 152


def ensure_face_landmarker_model(cfg: Config, logger: logging.Logger) -> str:
    if os.path.exists(cfg.FACE_LANDMARKER_MODEL):
        return cfg.FACE_LANDMARKER_MODEL

    logger.info("Downloading MediaPipe face landmarker model...")
    try:
        urllib.request.urlretrieve(cfg.FACE_LANDMARKER_URL, cfg.FACE_LANDMARKER_MODEL)
    except Exception as exc:
        logger.critical(f"Failed to download face landmarker model: {exc}")
        sys.exit(1)

    logger.info(f"Model ready: {cfg.FACE_LANDMARKER_MODEL}")
    return cfg.FACE_LANDMARKER_MODEL


def create_face_landmarker(cfg: Config, logger: logging.Logger):
    model_path = ensure_face_landmarker_model(cfg, logger)
    base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.65,
        min_face_presence_confidence=0.65,
        min_tracking_confidence=0.65,
    )
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)


def get_camera_backend_candidates(preferred: str):
    backend_map = {
        'default': ("default", None),
        'dshow': ("dshow", cv2.CAP_DSHOW),
        'msmf': ("msmf", cv2.CAP_MSMF),
    }

    if preferred != 'auto':
        return [backend_map[preferred]]

    if os.name == 'nt':
        # Prefer Windows-native capture APIs before the default auto-probe.
        return [backend_map['dshow'], backend_map['msmf'], backend_map['default']]

    return [backend_map['default']]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def get_processing_size(width: int, height: int, target_width: int):
    if width <= target_width:
        return width, height
    scale = target_width / float(width)
    return target_width, max(1, int(height * scale))


def configure_camera_capture(cap, cfg: Config, logger: logging.Logger):
    """Ask the webcam for a sharper stream and report what was actually accepted."""
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    try:
        cap.set(cv2.CAP_PROP_FPS, cfg.CAMERA_FPS)
    except Exception:
        pass

    autofocus_prop = getattr(cv2, "CAP_PROP_AUTOFOCUS", None)
    if autofocus_prop is not None:
        try:
            cap.set(autofocus_prop, 1)
        except Exception:
            pass

    # MJPG often unlocks HD modes on USB webcams on Windows.
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    except Exception:
        pass

    candidates = [
        (cfg.CAMERA_WIDTH, cfg.CAMERA_HEIGHT),
        (1920, 1080),
        (1280, 720),
        (960, 540),
    ]

    seen = set()
    for width, height in candidates:
        if (width, height) in seen:
            continue
        seen.add((width, height))
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        except Exception:
            continue

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if actual_w >= int(width * 0.8) and actual_h >= int(height * 0.8):
            break

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or cfg.CAMERA_WIDTH)
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or cfg.CAMERA_HEIGHT)
    actual_fps = cap.get(cv2.CAP_PROP_FPS) or cfg.CAMERA_FPS
    logger.info(f"Camera stream configured at {actual_w}x{actual_h} @ {actual_fps:.1f} FPS")
    return actual_w, actual_h, actual_fps


def build_camera_index_candidates(requested_index: int, scan_max: int):
    indices = [requested_index]
    for idx in range(scan_max + 1):
        if idx not in indices:
            indices.append(idx)
    return indices


def try_open_camera(index: int, backend_name: str, backend_value, logger: logging.Logger):
    cap = None
    try:
        cap = cv2.VideoCapture(index) if backend_value is None else cv2.VideoCapture(index, backend_value)
        if cap is not None and cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            return cap
        if cap is not None:
            cap.release()
    except Exception as exc:
        logger.warning(f"Camera backend {backend_name} failed on index {index}: {exc}")
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
    return None


def open_camera(cfg: Config, logger: logging.Logger):
    """Try a preferred camera first, then auto-scan indices/backends."""
    attempts = []
    indices = build_camera_index_candidates(cfg.CAM_INDEX, cfg.CAMERA_SCAN_MAX)
    backends = get_camera_backend_candidates(cfg.CAMERA_BACKEND)

    for index in indices:
        for backend_name, backend_value in backends:
            cap = try_open_camera(index, backend_name, backend_value, logger)
            attempts.append(f"{backend_name}:{index}")
            if cap is not None:
                logger.info(f"Camera opened on index {index} using backend: {backend_name}")
                return cap, index, backend_name

    logger.critical(
        "Cannot open any camera. Tried "
        + ", ".join(attempts)
        + ". Close other camera apps, allow camera access in Windows privacy settings, "
          "or try a different index with --cam."
    )
    return None, None, None


class CameraStream:
    """Continuously reads frames in a background thread so the UI stays responsive."""

    def __init__(self, cap, logger: logging.Logger):
        self.cap = cap
        self.logger = logger
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._frame = None
        self._last_frame_time = 0.0
        self._last_read_error = None
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self):
        while not self._stop_event.is_set():
            try:
                ok, frame = self.cap.read()
            except Exception as exc:
                ok, frame = False, None
                self._last_read_error = str(exc)

            now = time.time()
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                    self._last_frame_time = now
                self._last_read_error = None
            else:
                if self._last_read_error is None:
                    self._last_read_error = "Camera read returned no frame."
                time.sleep(0.02)

    def read(self):
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            last_frame_time = self._last_frame_time
        return frame, last_frame_time, self._last_read_error

    def close(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self.cap.release()
        except Exception:
            pass


def render_status_frame(lines, size=(640, 480), accent=(0, 140, 255)):
    frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    frame[:] = (16, 22, 30)
    cv2.rectangle(frame, (24, 24), (size[0] - 24, size[1] - 24), (72, 88, 106), 1)
    cv2.rectangle(frame, (40, 40), (size[0] - 40, size[1] - 40), (23, 30, 40), -1)
    overlay = frame.copy()
    cv2.rectangle(overlay, (40, 40), (size[0] - 40, 88), accent, -1)
    cv2.addWeighted(overlay, 0.22, frame, 0.78, 0, frame)
    cv2.rectangle(frame, (40, 40), (size[0] - 40, 88), accent, 3)
    cv2.putText(frame, "Driver Drowsiness Detection", (56, 73),
                cv2.FONT_HERSHEY_SIMPLEX, 0.82, (244, 247, 250), 2, cv2.LINE_AA)
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (56, 145 + i * 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.70, (228, 235, 242), 2, cv2.LINE_AA)
    return frame


# ════════════════════════════════════════════════════
#  LOGGING SETUP
# ════════════════════════════════════════════════════
def setup_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("DDS")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s │ %(levelname)-8s │ %(message)s",
                            datefmt="%H:%M:%S")
    fh = logging.FileHandler(cfg.LOG_FILE, encoding='utf-8')
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ════════════════════════════════════════════════════
#  AUDIO MANAGER — cross-platform beeping
# ════════════════════════════════════════════════════
class AudioManager:
    def __init__(self, mute=False):
        self.mute         = mute
        self._playing     = False
        self._stop_event  = threading.Event()
        self._thread      = None
        self._backend     = AUDIO_BACKEND
        self._lock        = threading.Lock()

        # Pre-generate beep waveform for pygame backend
        self._pygame_buf = None
        if self._backend == 'pygame':
            try:
                freq, dur_ms = 1000, 400
                sample_rate  = 44100
                n_samples    = int(sample_rate * dur_ms / 1000)
                t   = np.linspace(0, dur_ms / 1000, n_samples, False)
                wav = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
                self._pygame_buf = pygame.sndarray.make_sound(wav)
            except Exception:
                self._backend = 'system'

    def _beep_once(self):
        try:
            if self._backend == 'winsound':
                winsound.Beep(1000, 400)
            elif self._backend == 'pygame' and self._pygame_buf:
                self._pygame_buf.play()
                time.sleep(0.4)
            else:
                # Fallback: print terminal bell
                print('\a', end='', flush=True)
                time.sleep(0.5)
        except Exception:
            pass

    def _loop(self):
        while not self._stop_event.is_set():
            self._beep_once()
            time.sleep(0.1)

    def start(self):
        if self.mute:
            return
        with self._lock:
            if not self._playing:
                self._playing    = True
                self._stop_event = threading.Event()
                self._thread     = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

    def stop(self):
        with self._lock:
            if self._playing:
                self._playing = False
                self._stop_event.set()


# ════════════════════════════════════════════════════
#  ARDUINO MANAGER — with auto-reconnect thread
# ════════════════════════════════════════════════════
class ArduinoManager:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg       = cfg
        self.logger    = logger
        self._ser      = None
        self._port_name = None
        self._lock     = threading.Lock()
        self._last_sig = ''
        self._last_time= 0.0
        self.INTERVAL  = 0.1
        self._ready_at = 0.0
        self._stop_event = threading.Event()
        self._connect_thread = None

        if cfg.USE_ARDUINO:
            self._start_connect_thread()
            # Background reconnect thread
            t = threading.Thread(target=self._reconnect_loop, daemon=True)
            t.start()

    def _find_port(self):
        if not SERIAL_AVAILABLE:
            return None
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (p.description or '').lower()
            if any(k in desc for k in ['arduino', 'ch340', 'usb serial', 'usb-serial']):
                return p.device
        return None

    def _start_connect_thread(self):
        with self._lock:
            if self._connect_thread is not None and self._connect_thread.is_alive():
                return
            self._connect_thread = threading.Thread(target=self._connect, daemon=True)
            self._connect_thread.start()

    def _connect(self):
        if not SERIAL_AVAILABLE:
            return
        ports_to_try = [self.cfg.SERIAL_PORT]
        auto = self._find_port()
        if auto and auto not in ports_to_try:
            ports_to_try.append(auto)

        errors = []
        for port in ports_to_try:
            if self._stop_event.is_set():
                return
            try:
                ser = serial.Serial(
                    port,
                    self.cfg.BAUD_RATE,
                    timeout=0.2,
                    write_timeout=0.2,
                )
                old_ser = None
                with self._lock:
                    if self._stop_event.is_set():
                        ser.close()
                        return
                    old_ser = self._ser
                    self._ser = ser
                    self._port_name = port
                    self._ready_at = time.time() + self.cfg.ARDUINO_WARMUP_SEC
                if old_ser and old_ser is not ser:
                    try:
                        old_ser.close()
                    except Exception:
                        pass
                self.logger.info(
                    f"Arduino connected on {port} "
                    f"(warming up for {self.cfg.ARDUINO_WARMUP_SEC:.1f}s in background)"
                )
                return
            except Exception as exc:
                errors.append(f"{port}: {exc}")

        detail = " | ".join(errors[:2]) if errors else "not detected"
        self.logger.debug(f"Arduino unavailable — software-only mode. {detail}")

    def _reconnect_loop(self):
        """Silently try to reconnect every 10s if disconnected."""
        while not self._stop_event.wait(10):
            with self._lock:
                connected = self._ser is not None and self._ser.is_open
            if not connected:
                self.logger.debug("Attempting Arduino reconnect...")
                self._start_connect_thread()

    def send(self, signal: str):
        """Send 'D' (drowsy) or 'N' (normal) — rate-limited & dedup."""
        now = time.time()
        if signal == self._last_sig and now - self._last_time < self.INTERVAL:
            return
        with self._lock:
            ser = self._ser
            ready_at = self._ready_at
        if ser and ser.is_open and now >= ready_at:
            try:
                ser.write(signal.encode())
                self._last_sig  = signal
                self._last_time = now
            except Exception:
                self.logger.error("Arduino write failed — marked disconnected.")
                with self._lock:
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
                    self._port_name = None

    def close(self):
        self._stop_event.set()
        with self._lock:
            if self._ser:
                try:
                    self._ser.write(b'N')
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
            self._port_name = None
        if self._connect_thread is not None and self._connect_thread.is_alive():
            self._connect_thread.join(timeout=0.5)

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._ser and self._ser.is_open and time.time() >= self._ready_at)

    @property
    def port_name(self) -> str:
        with self._lock:
            return self._port_name or "--"


# ════════════════════════════════════════════════════
#  MATH — EAR, MAR
# ════════════════════════════════════════════════════
def get_ear(landmarks, eye_indices, w, h) -> float:
    """Eye Aspect Ratio: (|p2-p6| + |p3-p5|) / (2·|p1-p4|)"""
    pts = []
    for idx in eye_indices:
        lm = landmarks[idx]
        pts.append(np.array([lm.x * w, lm.y * h]))
    v1  = np.linalg.norm(pts[1] - pts[5])
    v2  = np.linalg.norm(pts[2] - pts[4])
    h_d = np.linalg.norm(pts[0] - pts[3])
    return (v1 + v2) / (2.0 * h_d + 1e-6)


def get_mar(landmarks, w, h) -> float:
    """Robust Mouth Aspect Ratio using multiple lip gaps for yawn detection."""
    def pt(i):
        lm = landmarks[i]
        return np.array([lm.x * w, lm.y * h])

    left_gap = np.linalg.norm(pt(MOUTH_UPPER_LEFT) - pt(MOUTH_LOWER_LEFT))
    center_gap = np.linalg.norm(pt(MOUTH_TOP) - pt(MOUTH_BOTTOM))
    right_gap = np.linalg.norm(pt(MOUTH_UPPER_RIGHT) - pt(MOUTH_LOWER_RIGHT))
    mouth_width = np.linalg.norm(pt(MOUTH_OUTER_LEFT) - pt(MOUTH_OUTER_RIGHT))
    return (left_gap + center_gap + right_gap) / (2.0 * mouth_width + 1e-6)


def get_mouth_open_ratio(landmarks, h) -> float:
    """Vertical mouth opening normalized by face height."""
    mouth_top = landmarks[MOUTH_TOP].y * h
    mouth_bottom = landmarks[MOUTH_BOTTOM].y * h
    face_top = landmarks[FOREHEAD_TOP].y * h
    face_bottom = landmarks[CHIN_BOTTOM].y * h
    face_height = abs(face_bottom - face_top) + 1e-6
    return abs(mouth_bottom - mouth_top) / face_height


def get_nose_y_norm(landmarks, w, h) -> float:
    """Normalized nose Y relative to face height (for nod detection)."""
    nose = landmarks[NOSE_TIP]
    face_top = landmarks[FOREHEAD_TOP]
    face_bottom = landmarks[CHIN_BOTTOM]
    face_top_y = face_top.y * h
    face_h = abs(face_bottom.y - face_top.y) * h + 1e-6
    nose_y = nose.y * h
    return (nose_y - face_top_y) / face_h


# ════════════════════════════════════════════════════
#  PERCLOS — Percentage Eye Closure (industry standard)
#  PERCLOS > 15% over 60s = clinically drowsy
# ════════════════════════════════════════════════════
class PerclosTracker:
    def __init__(self, window_sec: int, fps_est: float = 20.0):
        max_len = int(window_sec * fps_est)
        self._q = deque(maxlen=max_len)
        self._closed_count = 0

    def update(self, eyes_closed: bool):
        value = 1 if eyes_closed else 0
        if len(self._q) == self._q.maxlen:
            self._closed_count -= self._q[0]
        self._q.append(value)
        self._closed_count += value

    @property
    def value(self) -> float:
        if not self._q:
            return 0.0
        # Prevent false positives by assuming at least 25% of the window has passed
        effective_len = max(len(self._q), int(self._q.maxlen * 0.25))
        return self._closed_count / effective_len

    @property
    def percent(self) -> int:
        return int(self.value * 100)


# ════════════════════════════════════════════════════
#  BLINK DETECTOR — tracks blinks per minute
#  Normal: 12-20 bpm.  >25 or <8 = fatigue signals
# ════════════════════════════════════════════════════
class BlinkTracker:
    def __init__(self, window_sec: int = 60, min_blink_sec: float = 0.06, max_blink_sec: float = 0.45):
        self._window = window_sec
        self._timestamps = deque()
        self._closed_since = None
        self._is_closed = False
        self._min_blink_sec = min_blink_sec
        self._max_blink_sec = max_blink_sec
        self.total_blinks = 0

    def update(self, ear: float, threshold: float, sample_time: float = None):
        if sample_time is None:
            sample_time = time.time()
        is_closed = ear < threshold

        if is_closed:
            if not self._is_closed:
                self._closed_since = sample_time
            self._is_closed = True
        elif self._is_closed and self._closed_since is not None:
            closure_sec = sample_time - self._closed_since
            if self._min_blink_sec <= closure_sec <= self._max_blink_sec:
                self._timestamps.append(sample_time)
                self.total_blinks += 1
            self._closed_since = None
            self._is_closed = False
        else:
            self._closed_since = None
            self._is_closed = False

        # Remove old timestamps outside window
        cutoff = sample_time - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def reset_current(self):
        self._closed_since = None
        self._is_closed = False

    @property
    def blinks_per_min(self) -> int:
        return len(self._timestamps)


class SustainedStateTracker:
    """Tracks how long a condition stays active before it becomes a real alert."""

    def __init__(self, active_after_sec: float, clear_after_sec: float = 0.25):
        self.active_after_sec = active_after_sec
        self.clear_after_sec = clear_after_sec
        self._active_since = None
        self._clear_since = None
        self.is_active = False
        self.active_duration = 0.0

    def update(self, condition: bool, sample_time: float = None) -> float:
        if sample_time is None:
            sample_time = time.time()

        if condition:
            if self._active_since is None:
                self._active_since = sample_time
            self._clear_since = None
            self.active_duration = max(0.0, sample_time - self._active_since)
            self.is_active = self.active_duration >= self.active_after_sec
            return self.active_duration

        if self._active_since is not None:
            if self._clear_since is None:
                self._clear_since = sample_time
            if sample_time - self._clear_since >= self.clear_after_sec:
                self.reset()
                return 0.0
            self.active_duration = max(0.0, sample_time - self._active_since)
            return self.active_duration

        self.active_duration = 0.0
        self.is_active = False
        return 0.0

    def reset(self):
        self._active_since = None
        self._clear_since = None
        self.active_duration = 0.0
        self.is_active = False


# ════════════════════════════════════════════════════
#  HEAD NOD DETECTOR
#  Sudden drop in nose Y-norm → forward nod → micro-sleep sign
# ════════════════════════════════════════════════════
class NodDetector:
    def __init__(self, threshold: float = 0.08, history: int = 15):
        self.threshold = threshold
        self._q = deque(maxlen=history)
        self.nods_detected = 0
        self.is_nodding = False

    def update(self, nose_y_norm: float) -> bool:
        self._q.append(nose_y_norm)
        if len(self._q) < 5:
            self.is_nodding = False
            return False
        baseline = np.mean(list(self._q)[:5])
        current  = nose_y_norm
        # Nose drops significantly below recent average
        nod = (current - baseline) > self.threshold
        if nod and not self.is_nodding:
            self.nods_detected += 1
        self.is_nodding = nod
        return nod


# ════════════════════════════════════════════════════
#  ALERT MANAGER — per-type cooldown + deduplicated logging
# ════════════════════════════════════════════════════
class AlertManager:
    TYPES = ['drowsy', 'yawn', 'perclos', 'nod', 'face_lost']

    def __init__(self, cooldown: int, logger: logging.Logger):
        self.cooldown = cooldown
        self.logger   = logger
        self._last    = {t: 0.0 for t in self.TYPES}
        self.counts   = {t: 0   for t in self.TYPES}

    def trigger(self, alert_type: str, detail: str = '') -> bool:
        """Returns True if alert fires (not in cooldown)."""
        now = time.time()
        if now - self._last[alert_type] >= self.cooldown:
            self._last[alert_type] = now
            self.counts[alert_type] += 1
            n = self.counts[alert_type]
            self.logger.warning(f"ALERT [{alert_type.upper()} #{n}] {detail}")
            return True
        return False

    @property
    def total(self):
        return sum(self.counts.values())


# ════════════════════════════════════════════════════
#  SCREENSHOT SAVER
# ════════════════════════════════════════════════════
class ScreenshotSaver:
    def __init__(self, folder: str, enabled: bool = True):
        self.folder  = folder
        self.enabled = enabled
        self._saved  = 0
        self._last_label = None
        self._last_time = 0.0
        self._queue = queue.Queue(maxsize=8)
        self._stop_event = threading.Event()
        self._worker = None

        if self.enabled:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def _worker_loop(self):
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                path, image = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                cv2.imwrite(path, image)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def save(self, frame: np.ndarray, label: str):
        if not self.enabled:
            return
        now = time.time()
        if self._last_label == label and now - self._last_time < 1.0:
            return
        self._saved += 1
        self._last_label = label
        self._last_time = now
        ts   = datetime.now().strftime('%H%M%S_%f')[:10]
        name = f"{label}_{ts}.jpg"
        path = os.path.join(self.folder, name)
        try:
            self._queue.put_nowait((path, frame.copy()))
        except queue.Full:
            pass

    @property
    def count(self):
        return self._saved

    def close(self):
        if not self.enabled:
            return
        self._stop_event.set()
        try:
            self._queue.join()
        except Exception:
            pass
        if self._worker is not None:
            self._worker.join(timeout=1.0)


# ════════════════════════════════════════════════════
#  HUD RENDERER — all drawing on the frame
# ════════════════════════════════════════════════════
class HUDRenderer:
    C_BG      = (16, 22, 30)
    C_PANEL   = (23, 30, 40)
    C_BORDER  = (74, 89, 107)
    C_TEXT    = (244, 247, 250)
    C_MUTED   = (162, 174, 188)
    C_OK      = (84, 189, 96)
    C_DANGER  = (70, 86, 228)
    C_WARN    = (0, 182, 255)
    C_INFO    = (196, 176, 72)
    C_GRAPH   = (118, 205, 255)
    C_GRAPH_FILL = (56, 109, 162)
    C_GRID    = (53, 67, 82)
    C_TRACK   = (46, 56, 68)
    C_TEAL    = (180, 205, 72)

    def __init__(self, ear_threshold: float, mar_threshold: float):
        self.ear_threshold = ear_threshold
        self.mar_threshold = mar_threshold
        self._ear_history  = deque(maxlen=150)  # last ~5 seconds at 30fps

    def push_ear(self, ear: float):
        self._ear_history.append(ear)

    # ── helpers ──────────────────────────────────────
    def _alpha_rect(self, frame, x1, y1, x2, y2, color, alpha=0.55):
        fh, fw = frame.shape[:2]
        x1 = max(0, min(fw, int(x1)))
        x2 = max(0, min(fw, int(x2)))
        y1 = max(0, min(fh, int(y1)))
        y2 = max(0, min(fh, int(y2)))
        if x2 <= x1 or y2 <= y1:
            return
        sub = frame[y1:y2, x1:x2]
        rect = np.full_like(sub, color)
        cv2.addWeighted(rect, alpha, sub, 1 - alpha, 0, sub)
        frame[y1:y2, x1:x2] = sub

    def _text(self, frame, txt, pos, scale=0.50, color=None, thickness=1):
        color = color or self.C_TEXT
        cv2.putText(frame, txt, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

    def _panel(self, frame, x, y, w, h, title, accent, subtitle=None):
        self._alpha_rect(frame, x, y, x + w, y + h, self.C_PANEL, 0.72)
        cv2.rectangle(frame, (x, y), (x + w, y + h), self.C_BORDER, 1)
        cv2.rectangle(frame, (x, y), (x + w, y + 5), accent, -1)
        self._text(frame, title, (x + 12, y + 25), 0.62, self.C_TEXT, 2)
        if subtitle:
            self._text(frame, subtitle, (x + 12, y + 45), 0.40, self.C_MUTED, 1)

    def _chip(self, frame, x, y, label, color, active=True):
        scale = 0.40
        thickness = 1
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        pad_x = 10
        pad_y = 6
        w = tw + pad_x * 2
        h = th + pad_y * 2
        fill = color if active else self.C_TRACK
        alpha = 0.22 if active else 0.70
        self._alpha_rect(frame, x, y, x + w, y + h, fill, alpha)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color if active else self.C_BORDER, 1)
        self._text(frame, label, (x + pad_x, y + h - 7), scale, self.C_TEXT if active else self.C_MUTED, thickness)
        return w

    def _meter(self, frame, x, y, w, label, value, threshold, min_value, max_value, color, alert=False):
        bar_y = y + 18
        bar_h = 10
        value_norm = clamp((value - min_value) / (max_value - min_value + 1e-6), 0.0, 1.0)
        threshold_norm = clamp((threshold - min_value) / (max_value - min_value + 1e-6), 0.0, 1.0)
        fill_w = int((w - 2) * value_norm)
        threshold_x = x + 1 + int((w - 2) * threshold_norm)

        self._text(frame, label, (x, y + 2), 0.42, self.C_MUTED)
        self._text(frame, f"{value:.3f}", (x + w - 54, y + 2), 0.44, color if alert else self.C_TEXT, 1)
        cv2.rectangle(frame, (x, bar_y), (x + w, bar_y + bar_h), self.C_TRACK, -1)
        if fill_w > 0:
            cv2.rectangle(frame, (x + 1, bar_y + 1), (x + 1 + fill_w, bar_y + bar_h - 1), color, -1)
        cv2.line(frame, (threshold_x, bar_y - 2), (threshold_x, bar_y + bar_h + 2), self.C_WARN, 1)
        cv2.rectangle(frame, (x, bar_y), (x + w, bar_y + bar_h), self.C_BORDER, 1)

    def _draw_ear_graph(self, frame, x, y, w, h, ear_threshold, current_ear):
        plot_x = x + 10
        plot_y = y + 28
        plot_w = w - 20
        plot_h = h - 38

        for frac in (0.25, 0.5, 0.75):
            gy = int(plot_y + plot_h * frac)
            cv2.line(frame, (plot_x, gy), (plot_x + plot_w, gy), self.C_GRID, 1)

        history = tuple(self._ear_history)
        if len(history) >= 2:
            pts = []
            for i, ear in enumerate(history):
                px = plot_x + int(i * (plot_w - 1) / max(1, len(history) - 1))
                py = plot_y + plot_h - int(clamp(ear / 0.45, 0.0, 1.0) * (plot_h - 2))
                pts.append((px, py))

            sub = frame[y:y + h, x:x + w]
            overlay = sub.copy()
            local_pts = np.array([(px - x, py - y) for px, py in pts], dtype=np.int32)
            fill_pts = np.vstack((
                local_pts,
                np.array([[pts[-1][0] - x, plot_y + plot_h - y], [pts[0][0] - x, plot_y + plot_h - y]], dtype=np.int32)
            ))
            cv2.fillPoly(overlay, [fill_pts], self.C_GRAPH_FILL)
            cv2.addWeighted(overlay, 0.16, sub, 0.84, 0, sub)
            cv2.polylines(frame, [np.array(pts, dtype=np.int32)], False, self.C_GRAPH, 2)

        thr_y = plot_y + plot_h - int(clamp(ear_threshold / 0.45, 0.0, 1.0) * (plot_h - 2))
        cv2.line(frame, (plot_x, thr_y), (plot_x + plot_w, thr_y), self.C_WARN, 1)
        self._text(frame, "EAR trend", (x + 10, y + 18), 0.40, self.C_MUTED)
        self._text(frame, f"{current_ear:.3f}", (x + w - 52, y + 18), 0.40, self.C_TEXT)

    def _draw_callout(self, frame, x, y, w, headline, detail, color):
        h = 58
        self._alpha_rect(frame, x, y, x + w, y + h, self.C_PANEL, 0.78)
        cv2.rectangle(frame, (x, y), (x + 6, y + h), color, -1)
        cv2.rectangle(frame, (x, y), (x + w, y + h), self.C_BORDER, 1)
        self._text(frame, headline, (x + 16, y + 24), 0.58, color, 2)
        self._text(frame, detail, (x + 16, y + 45), 0.41, self.C_TEXT)

    def draw(self, frame: np.ndarray, state: dict):
        fh, fw = frame.shape[:2]

        ear = state['ear']
        mar = state['mar']
        eye_ct = state['eye_ct']
        yawn_ct = state['yawn_ct']
        ear_consec = state['ear_consec']
        yawn_consec = state['yawn_consec']
        ear_threshold = state['ear_threshold']
        mar_threshold = state['mar_threshold']
        mouth_gap = state['mouth_gap']
        is_drowsy = state['is_drowsy']
        is_yawning = state['is_yawning']
        is_nodding = state['is_nodding']
        face_lost = state['face_lost']
        bpm = state['blinks_per_min']
        total_blinks = state['total_blinks']
        nods = state['nods']
        alert_total = state['alert_total']
        perclos_pct = state['perclos_pct']
        perclos_alert = state['perclos_alert']
        fps = state.get('fps', 0.0)
        process_every = state.get('process_every', 1)
        camera_label = state.get('camera_label', 'Camera')
        face_tracked = state.get('face_tracked', False)
        arduino_connected = state.get('arduino_connected', False)
        arduino_port = state.get('arduino_port', '--')

        if is_drowsy:
            status_title = "Drowsy Alert"
            status_detail = f"Eyes closed {eye_ct:.1f}s of {ear_consec:.1f}s threshold"
            status_color = self.C_DANGER
        elif perclos_alert:
            status_title = "Fatigue Rising"
            status_detail = f"PERCLOS elevated to {perclos_pct}% in the rolling window"
            status_color = self.C_WARN
        elif face_lost:
            status_title = "Face Lost"
            status_detail = "Re-center your face so tracking can recover"
            status_color = self.C_WARN
        elif is_nodding:
            status_title = "Head Nod Detected"
            status_detail = "Forward head drop suggests a possible microsleep"
            status_color = self.C_WARN
        elif is_yawning:
            status_title = "Fatigue Sign"
            status_detail = f"Yawn sustained for {yawn_ct:.1f}s of {yawn_consec:.1f}s"
            status_color = self.C_INFO
        elif not face_tracked:
            status_title = "Scanning"
            status_detail = "Looking for a stable face lock"
            status_color = self.C_INFO
        else:
            status_title = "Monitoring"
            status_detail = "Stable tracking and normal driver state"
            status_color = self.C_OK

        margin = 14
        left_w = min(390, max(300, fw // 3))
        right_w = min(320, max(250, fw // 4))
        top_h = min(252, max(230, fh // 2))
        right_x = fw - right_w - margin

        self._panel(frame, margin, margin, left_w, top_h, "Driver State", status_color, status_detail)
        self._text(frame, status_title, (margin + 12, margin + 78), 0.86, status_color, 2)

        meter_x = margin + 12
        meter_w = left_w - 24
        self._meter(frame, meter_x, margin + 102, meter_w, "EAR  eye openness", ear, ear_threshold, 0.0, 0.45, self.C_DANGER if ear < ear_threshold else self.C_OK, ear < ear_threshold)
        self._meter(frame, meter_x, margin + 148, meter_w, "MAR  mouth openness", mar, mar_threshold, 0.0, 1.0, self.C_WARN if mar > mar_threshold else self.C_TEAL, mar > mar_threshold)
        self._meter(frame, meter_x, margin + 194, meter_w, "PERCLOS  rolling fatigue", perclos_pct / 100.0, 0.15, 0.0, 1.0, self.C_WARN if perclos_alert else self.C_OK, perclos_alert)

        info_y = margin + top_h - 34
        self._text(frame, f"Blink {bpm} bpm   Total {total_blinks}", (meter_x, info_y), 0.42, self.C_TEXT)
        self._text(frame, f"Nods {nods}   Alerts {alert_total}   Gap {mouth_gap:.3f}", (meter_x, info_y + 20), 0.40, self.C_MUTED)

        self._panel(frame, right_x, margin, right_w, top_h, "System View", self.C_GRAPH, camera_label)
        chip_y = margin + 56
        chip_x = right_x + 12
        chip_gap = 8
        chip_x += self._chip(frame, chip_x, chip_y, "Face Lock" if face_tracked else "Searching", self.C_OK if face_tracked else self.C_INFO, True) + chip_gap
        self._chip(frame, chip_x, chip_y, f"Arduino {arduino_port}", self.C_TEAL if arduino_connected else self.C_WARN, arduino_connected)
        self._text(frame, f"Runtime {fps:.0f} FPS  |  Detect every {process_every} frame(s)",
                   (right_x + 12, margin + 90), 0.40, self.C_MUTED)
        self._draw_ear_graph(frame, right_x + 10, margin + 102, right_w - 20, top_h - 130, ear_threshold, ear)

        alerts = []
        if is_drowsy:
            alerts.append(("Wake Up", "Sustained eye closure detected. Pull over safely if needed.", self.C_DANGER))
        if perclos_alert:
            alerts.append(("High Fatigue", f"PERCLOS is {perclos_pct}%, above the drowsiness threshold.", self.C_WARN))
        if face_lost:
            alerts.append(("Face Not Visible", "Align yourself with the camera to resume tracking.", self.C_INFO))
        if is_nodding:
            alerts.append(("Head Nod", "Forward head movement suggests a possible microsleep.", self.C_WARN))
        if is_yawning:
            alerts.append(("Yawning", "A sustained yawn can be an early fatigue indicator.", self.C_INFO))

        if alerts:
            callout_w = min(fw - margin * 2, 620)
            callout_y = fh - margin - 58
            headline, detail, color = alerts[0]
            self._draw_callout(frame, margin, callout_y, callout_w, headline, detail, color)
            chip_x = margin
            chip_y = callout_y - 38
            for headline, _, color in alerts[1:4]:
                chip_x += self._chip(frame, chip_x, chip_y, headline, color, True) + 8
        else:
            footer_w = min(fw - margin * 2, 460)
            footer_y = fh - margin - 42
            self._alpha_rect(frame, margin, footer_y, margin + footer_w, footer_y + 32, self.C_PANEL, 0.66)
            cv2.rectangle(frame, (margin, footer_y), (margin + footer_w, footer_y + 32), self.C_BORDER, 1)
            self._text(frame, "Live monitoring active  |  Press Q to quit", (margin + 12, footer_y + 21), 0.43, self.C_MUTED)

        if is_nodding:
            cv2.putText(frame, "NOD", (fw // 2 - 36, fh // 2),
                        cv2.FONT_HERSHEY_DUPLEX, 1.25, self.C_WARN, 3, cv2.LINE_AA)

    # ── Eye/mouth landmark overlays ───────────────────
    def draw_landmarks(self, frame, lm, w, h, ear, mar, ear_threshold, mar_threshold):
        eye_col = self.C_DANGER if ear < ear_threshold else self.C_OK
        mouth_col = self.C_WARN if mar > mar_threshold else self.C_GRAPH
        point_r = 2 if w < 1200 else 3
        line_w = 1 if w < 1200 else 2

        for eye in [LEFT_EYE, RIGHT_EYE]:
            pts = []
            for idx in eye:
                x = int(lm[idx].x * w)
                y = int(lm[idx].y * h)
                pts.append((x, y))
                cv2.circle(frame, (x, y), point_r, eye_col, -1)
            hull = cv2.convexHull(np.array(pts))
            cv2.polylines(frame, [hull], True, eye_col, line_w)

        mouth_pts = []
        for idx in [
            MOUTH_OUTER_LEFT, MOUTH_OUTER_RIGHT,
            MOUTH_UPPER_LEFT, MOUTH_LOWER_LEFT,
            MOUTH_TOP, MOUTH_BOTTOM,
            MOUTH_UPPER_RIGHT, MOUTH_LOWER_RIGHT
        ]:
            x = int(lm[idx].x * w)
            y = int(lm[idx].y * h)
            mouth_pts.append((x, y))
            cv2.circle(frame, (x, y), point_r + 1, mouth_col, -1)
        cv2.polylines(frame, [cv2.convexHull(np.array(mouth_pts))], True, mouth_col, line_w)

        # Nose tip dot
        nx = int(lm[NOSE_TIP].x * w)
        ny = int(lm[NOSE_TIP].y * h)
        cv2.circle(frame, (nx, ny), point_r + 1, self.C_INFO, -1)
        cv2.circle(frame, (nx, ny), point_r + 4, self.C_INFO, 1)


# ════════════════════════════════════════════════════
#  SESSION STATS — for final report
# ════════════════════════════════════════════════════
class SessionStats:
    def __init__(self):
        self.start_time    = time.time()
        self.total_frames  = 0
        self.face_detected = 0
        self.ear_total     = 0.0
        self.mar_total     = 0.0

    def push(self, ear, mar, face_found):
        self.total_frames += 1
        if face_found:
            self.face_detected += 1
            self.ear_total += ear
            self.mar_total += mar

    def report(self, alerts: dict, blink_tracker: BlinkTracker, nod_det: NodDetector):
        dur = time.time() - self.start_time
        mm, ss = divmod(int(dur), 60)
        return {
            "session_duration_s": round(dur, 1),
            "session_duration_fmt": f"{mm}m {ss}s",
            "total_frames": self.total_frames,
            "face_detected_frames": self.face_detected,
            "avg_ear": round(self.ear_total / self.face_detected, 4) if self.face_detected else 0,
            "avg_mar": round(self.mar_total / self.face_detected, 4) if self.face_detected else 0,
            "total_blinks": blink_tracker.total_blinks,
            "total_nods": nod_det.nods_detected,
            "alerts": alerts,
            "total_alerts": sum(alerts.values()),
        }


# ════════════════════════════════════════════════════
#  MAIN DETECTION LOOP
# ════════════════════════════════════════════════════
def main():
    args   = parse_args()
    cfg    = Config(args)
    logger = setup_logger(cfg)
    window_name = "Driver Drowsiness Detection System v2.0"

    logger.info("═" * 60)
    logger.info("  DRIVER DROWSINESS DETECTION SYSTEM v2.0  —  STARTING")
    logger.info(f"  Audio backend : {AUDIO_BACKEND}")
    logger.info(f"  Arduino       : {'enabled' if cfg.USE_ARDUINO else 'disabled'}")
    logger.info(f"  EAR threshold : {cfg.EAR_THRESHOLD}  |  MAR: {cfg.MAR_THRESHOLD}")
    logger.info(f"  Camera        : requested index={cfg.CAM_INDEX}  backend={cfg.CAMERA_BACKEND}")
    logger.info(f"  Camera mode   : {cfg.CAMERA_WIDTH}x{cfg.CAMERA_HEIGHT} @ {cfg.CAMERA_FPS} FPS")
    logger.info(f"  Process every : {cfg.PROCESS_EVERY} frame(s)  |  process width={cfg.PROCESS_WIDTH}")
    logger.info(f"  Alert delays  : eyes={cfg.EYE_CLOSED_DROWSY_SEC:.1f}s  yawn={cfg.YAWN_MIN_SEC:.1f}s")
    logger.info("═" * 60)

    # ── Init components ───────────────────────────
    audio    = AudioManager(mute=cfg.MUTE)
    arduino  = ArduinoManager(cfg, logger)
    alerts   = AlertManager(cfg.ALERT_COOLDOWN, logger)
    perclos  = PerclosTracker(cfg.PERCLOS_WINDOW_SEC)
    blinks   = BlinkTracker(cfg.BLINK_RATE_WINDOW_SEC, cfg.MIN_BLINK_SEC, cfg.MAX_BLINK_SEC)
    nods     = NodDetector(cfg.NOD_THRESHOLD)
    shotsave = ScreenshotSaver(cfg.SHOT_DIR, cfg.SAVE_SCREENSHOTS)
    stats    = SessionStats()
    hud      = HUDRenderer(cfg.EAR_THRESHOLD, cfg.MAR_THRESHOLD)
    face_landmarker = None
    camera = None
    active_cam_index = None
    active_backend = None

    cv2.setUseOptimized(True)
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.imshow(window_name, render_status_frame([
        "Opening camera...",
        "Please wait a moment.",
        "Press Q to quit."
    ], accent=(0, 170, 255)))
    cv2.waitKey(1)

    # ── Webcam ────────────────────────────────────
    cap, active_cam_index, active_backend = open_camera(cfg, logger)
    if cap is None:
        cv2.imshow(window_name, render_status_frame([
            "No camera could be opened.",
            "Close other camera apps or try --cam 1.",
            "Check Windows camera privacy settings."
        ], accent=(0, 0, 180)))
        cv2.waitKey(1)
        audio.stop()
        arduino.close()
        shotsave.close()
        cv2.destroyAllWindows()
        return

    configure_camera_capture(cap, cfg, logger)
    camera = CameraStream(cap, logger)
    logger.info(f"Webcam opened on index {active_cam_index} with {active_backend}. Press Q to quit.")

    cv2.imshow(window_name, render_status_frame([
        f"Camera ready on index {active_cam_index} ({active_backend}).",
        "Loading face landmarker...",
        "Press Q to quit."
    ], accent=(0, 120, 220)))
    cv2.waitKey(1)

    # ── MediaPipe Face Landmarker ─────────────────
    face_landmarker = create_face_landmarker(cfg, logger)

    # ── State variables ───────────────────────────
    eye_state       = SustainedStateTracker(cfg.EYE_CLOSED_DROWSY_SEC, cfg.STATE_CLEAR_SEC)
    yawn_state      = SustainedStateTracker(cfg.YAWN_MIN_SEC, cfg.STATE_CLEAR_SEC)
    face_lost_since = None
    last_lm         = None
    last_ear        = 0.0
    last_mar        = 0.0
    last_mouth_gap  = 0.0
    last_nose_y     = 0.5
    effective_ear_threshold = cfg.EAR_THRESHOLD
    effective_mar_threshold = cfg.MAR_THRESHOLD
    ear_window      = deque(maxlen=cfg.EAR_SMOOTHING)
    mar_window      = deque(maxlen=cfg.MAR_SMOOTHING)
    mouth_gap_window = deque(maxlen=cfg.MAR_SMOOTHING)
    open_eye_samples = deque(maxlen=120)
    closed_mouth_samples = deque(maxlen=120)
    frame_idx       = 0
    fps_times       = deque(maxlen=30)
    last_face_seen_at = 0.0
    last_camera_retry = time.time()
    processing_cache_key = None
    proc_w = cfg.PROCESS_WIDTH
    proc_h = cfg.PROCESS_WIDTH
    proc_interp = cv2.INTER_LINEAR
    last_mp_timestamp = 0

    try:
        while True:
            now = time.time()
            frame, frame_time, read_error = camera.read()
            if frame is None:
                status_lines = [
                    "Waiting for camera frames...",
                    f"Camera index {active_cam_index} ({active_backend}) is not delivering frames.",
                    "The app will retry automatically. Press Q to quit."
                ]
                if read_error:
                    status_lines.insert(2, f"Last read error: {read_error[:60]}")
                cv2.imshow(window_name, render_status_frame(status_lines, accent=(0, 140, 255)))
                key = cv2.waitKey(30) & 0xFF
                if key == ord('q'):
                    logger.info("User pressed Q — shutting down.")
                    break
                if now - last_camera_retry >= cfg.CAMERA_FRAME_TIMEOUT_SEC:
                    logger.warning("Camera opened but no frames arrived. Reinitializing camera...")
                    last_camera_retry = now
                    camera.close()
                    cap, active_cam_index, active_backend = open_camera(cfg, logger)
                    if cap is None:
                        logger.error("Camera reinitialization failed.")
                        break
                    configure_camera_capture(cap, cfg, logger)
                    camera = CameraStream(cap, logger)
                continue

            if now - frame_time > cfg.CAMERA_FRAME_TIMEOUT_SEC:
                cv2.imshow(window_name, render_status_frame([
                    "Camera stream stalled.",
                    f"Last working source: index {active_cam_index} ({active_backend})",
                    "Trying to recover..."
                ], accent=(0, 90, 200)))
                key = cv2.waitKey(30) & 0xFF
                if key == ord('q'):
                    logger.info("User pressed Q — shutting down.")
                    break
                if now - last_camera_retry >= cfg.CAMERA_RETRY_COOLDOWN_SEC:
                    logger.warning("Camera stream stalled. Reinitializing camera...")
                    last_camera_retry = now
                    camera.close()
                    cap, active_cam_index, active_backend = open_camera(cfg, logger)
                    if cap is None:
                        logger.error("Camera reinitialization failed after stall.")
                        break
                    configure_camera_capture(cap, cfg, logger)
                    camera = CameraStream(cap, logger)
                continue

            frame     = cv2.flip(frame, 1)
            fh, fw    = frame.shape[:2]
            frame_idx += 1

            # ── FPS calculation ───────────────────
            fps_times.append(now)
            if len(fps_times) >= 2:
                fps = (len(fps_times) - 1) / (fps_times[-1] - fps_times[0] + 1e-6)
            else:
                fps = 0

            processed_face = False
            ear = last_ear
            mar = last_mar
            mouth_gap = last_mouth_gap

            # ── Run MediaPipe every N frames ──────
            if frame_idx % cfg.PROCESS_EVERY == 0:
                # Dual-res: downscale only as much as needed for reliable landmarks.
                if processing_cache_key != (fw, fh):
                    proc_w, proc_h = get_processing_size(fw, fh, cfg.PROCESS_WIDTH)
                    proc_interp = cv2.INTER_AREA if proc_w < fw else cv2.INTER_LINEAR
                    processing_cache_key = (fw, fh)
                small = cv2.resize(frame, (proc_w, proc_h), interpolation=proc_interp)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                current_mp_timestamp = int(time.monotonic() * 1000)
                if current_mp_timestamp <= last_mp_timestamp:
                    current_mp_timestamp = last_mp_timestamp + 1
                last_mp_timestamp = current_mp_timestamp

                results = face_landmarker.detect_for_video(
                    mp_image,
                    current_mp_timestamp
                )

                if results.face_landmarks:
                    lm = results.face_landmarks[0]
                    last_lm = lm
                    processed_face = True
                    face_lost_since = None
                    last_face_seen_at = now

                    l_ear = get_ear(lm, LEFT_EYE,  fw, fh)
                    r_ear = get_ear(lm, RIGHT_EYE, fw, fh)
                    ear = (l_ear + r_ear) / 2.0
                    mar = get_mar(lm, fw, fh)
                    mouth_gap = get_mouth_open_ratio(lm, fh)
                    nose_y = get_nose_y_norm(lm, fw, fh)

                    ear_window.append(ear)
                    mar_window.append(mar)
                    mouth_gap_window.append(mouth_gap)
                    ear = float(np.median(ear_window))
                    mar = float(np.mean(mar_window))
                    mouth_gap = float(np.mean(mouth_gap_window))

                    if ear > cfg.EAR_DYNAMIC_MIN + 0.03:
                        open_eye_samples.append(ear)
                    if mouth_gap < cfg.MOUTH_OPEN_MIN_RATIO * 0.85:
                        closed_mouth_samples.append(mar)

                    if len(open_eye_samples) >= 12:
                        eye_baseline = float(np.median(open_eye_samples))
                        effective_ear_threshold = min(
                            cfg.EAR_THRESHOLD,
                            max(cfg.EAR_DYNAMIC_MIN, eye_baseline * cfg.EAR_DYNAMIC_FACTOR)
                        )
                    if len(closed_mouth_samples) >= 12:
                        mouth_baseline = float(np.median(closed_mouth_samples))
                        effective_mar_threshold = min(
                            cfg.MAR_THRESHOLD,
                            max(cfg.MAR_DYNAMIC_MIN, mouth_baseline + cfg.MAR_DYNAMIC_OFFSET)
                        )

                    last_ear = ear
                    last_mar = mar
                    last_mouth_gap = mouth_gap
                    last_nose_y = nose_y

                    # Draw landmarks
                    hud.draw_landmarks(
                        frame,
                        lm,
                        fw,
                        fh,
                        ear,
                        mar,
                        effective_ear_threshold,
                        effective_mar_threshold,
                    )
                else:
                    if face_lost_since is None:
                        face_lost_since = now
            else:
                # Frame-skip: draw last known landmarks if available
                if last_lm is not None and (now - last_face_seen_at) < 0.5:
                    hud.draw_landmarks(
                        frame,
                        last_lm,
                        fw,
                        fh,
                        last_ear,
                        last_mar,
                        effective_ear_threshold,
                        effective_mar_threshold,
                    )

            face_metrics_available = last_lm is not None and (now - last_face_seen_at) < 0.5

            # ── Update trackers ───────────────────
            if face_metrics_available:
                hud.push_ear(ear)
            if face_metrics_available:
                eyes_closed = ear < effective_ear_threshold
                yawn_candidate = (
                    mar > effective_mar_threshold and
                    mouth_gap >= cfg.MOUTH_OPEN_MIN_RATIO
                )
                eye_closed_sec = eye_state.update(eyes_closed, now)
                yawn_open_sec = yawn_state.update(yawn_candidate, now)
                perclos.update(eyes_closed)
                blinks.update(ear, effective_ear_threshold, now)
                is_nodding = nods.update(last_nose_y) if processed_face else nods.is_nodding
            else:
                eye_state.reset()
                yawn_state.reset()
                blinks.reset_current()
                eye_closed_sec = 0.0
                yawn_open_sec = 0.0
                is_nodding = False
            is_drowsy = eye_state.is_active
            is_yawning = yawn_state.is_active
            stats.push(ear, mar, face_metrics_available)

            # ── Face lost detection ───────────────
            face_lost_alert = False
            face_lost_fired = False
            if face_lost_since is not None:
                lost_sec = now - face_lost_since
                if lost_sec >= cfg.FACE_LOST_ALERT_SEC:
                    face_lost_alert = True
                    face_lost_fired = alerts.trigger(
                        'face_lost',
                        f"Face not detected for {lost_sec:.0f}s"
                    )
                else:
                    cv2.putText(frame, f"No Face ({lost_sec:.1f}s)",
                                (fw // 2 - 100, fh // 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 165, 255), 2)

            # ── Trigger alerts ────────────────────
            drowsy_fired = False
            if is_drowsy:
                drowsy_fired = alerts.trigger(
                    'drowsy',
                    f"EAR={ear:.3f}  closed={eye_closed_sec:.2f}s  thr={effective_ear_threshold:.3f}"
                )

            yawn_fired = False
            if is_yawning:
                yawn_fired = alerts.trigger(
                    'yawn',
                    f"MAR={mar:.3f}  gap={mouth_gap:.3f}  open={yawn_open_sec:.2f}s"
                )

            nod_fired = False
            if is_nodding:
                nod_fired = alerts.trigger('nod', f"Nods total={nods.nods_detected}")

            perclos_alert = perclos.value >= cfg.PERCLOS_ALERT_LEVEL
            perclos_fired = False
            if perclos_alert:
                perclos_fired = alerts.trigger('perclos', f"PERCLOS={perclos.percent}%")

            # ── Audio + Arduino ───────────────────
            # Removing perclos_alert from any_alert so that heavy blinking doesn't stop the motor
            any_alert = is_drowsy or is_yawning or is_nodding or face_lost_alert
            if any_alert:
                audio.start()
                arduino.send('D')
                if drowsy_fired:
                    shotsave.save(frame, 'drowsy')
                if yawn_fired:
                    shotsave.save(frame, 'yawn')
                if nod_fired:
                    shotsave.save(frame, 'nod')
                if perclos_fired:
                    shotsave.save(frame, 'perclos')
                if face_lost_fired:
                    shotsave.save(frame, 'face_lost')
            else:
                audio.stop()
                arduino.send('N')

            # ── Draw HUD ──────────────────────────
            hud.draw(frame, {
                'ear':          ear,
                'mar':          mar,
                'eye_ct':       eye_closed_sec,
                'yawn_ct':      yawn_open_sec,
                'ear_consec':   cfg.EYE_CLOSED_DROWSY_SEC,
                'yawn_consec':  cfg.YAWN_MIN_SEC,
                'ear_threshold': effective_ear_threshold,
                'mar_threshold': effective_mar_threshold,
                'mouth_gap':    mouth_gap,
                'is_drowsy':    is_drowsy,
                'is_yawning':   is_yawning,
                'is_nodding':   is_nodding,
                'face_lost':    face_lost_alert,
                'blinks_per_min': blinks.blinks_per_min,
                'total_blinks': blinks.total_blinks,
                'nods':         nods.nods_detected,
                'alert_total':  alerts.total,
                'perclos_pct':  perclos.percent,
                'perclos_alert':perclos_alert,
                'fps':          fps,
                'process_every': cfg.PROCESS_EVERY,
                'camera_label': f"Cam {active_cam_index} · {active_backend}",
                'face_tracked': face_metrics_available,
                'arduino_connected': arduino.connected,
                'arduino_port': arduino.port_name,
            })

            cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("User pressed Q — shutting down.")
                break
                
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    logger.info("Window closed by user clicking X.")
                    break
            except Exception:
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by Ctrl+C.")

    finally:
        # ── Cleanup ───────────────────────────────
        audio.stop()
        arduino.close()
        shotsave.close()
        if face_landmarker is not None:
            face_landmarker.close()
        if camera is not None:
            camera.close()
        cv2.destroyAllWindows()

        # ── Session report ────────────────────────
        report = stats.report(alerts.counts, blinks, nods)
        logger.info("─" * 50)
        logger.info("  SESSION REPORT")
        logger.info(f"  Duration      : {report['session_duration_fmt']}")
        logger.info(f"  Total frames  : {report['total_frames']}")
        logger.info(f"  Avg EAR       : {report['avg_ear']}")
        logger.info(f"  Total blinks  : {report['total_blinks']}")
        logger.info(f"  Nods detected : {report['total_nods']}")
        logger.info(f"  Alerts        : {report['total_alerts']}")
        for k, v in report['alerts'].items():
            if v:
                logger.info(f"    {k:12s} : {v}")
        logger.info(f"  Screenshots   : {shotsave.count}")
        logger.info(f"  Log saved     : {cfg.LOG_FILE}")
        logger.info("─" * 50)

        # Save JSON report
        with open(cfg.REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        logger.info(f"  JSON report   : {cfg.REPORT_FILE}")
        logger.info("Goodbye! Drive safe.")


# ════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
