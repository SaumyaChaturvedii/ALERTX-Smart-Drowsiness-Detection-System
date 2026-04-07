import cv2
import mediapipe as mp
import time
import os
import sys
import urllib.request
import logging

from utils.config import cfg
from core.trackers import FacialMetricsTracker, BlinkTracker, PerclosTracker, NodTracker
from core.scorer import FatigueScorer
from ui.dashboard import DashboardUI
from io.camera import ThreadedCamera
from io.arduino import ArduinoManager
from io.audio import AudioManager
from utils.video_saver import AsyncVideoSaver

def ensure_model():
    if not os.path.exists(cfg.FACE_LANDMARKER_MODEL):
        print("Downloading MediaPipe face landmarker model...")
        url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
        urllib.request.urlretrieve(url, cfg.FACE_LANDMARKER_MODEL)

def create_face_landmarker():
    ensure_model()
    base_options = mp.tasks.BaseOptions(model_asset_path=cfg.FACE_LANDMARKER_MODEL)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.65,
        min_face_presence_confidence=0.65,
        min_tracking_confidence=0.65,
    )
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)

def main():
    logger = logging.getLogger("DDS_v3")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    logger.info("Initializing DDS v3 (Production-Grade)...")
    
    # Initialize Core modules
    camera = ThreadedCamera(cfg)
    audio = AudioManager(cfg)
    arduino = ArduinoManager(cfg, logger)
    video_saver = AsyncVideoSaver(cfg)
    ui = DashboardUI(cfg)
    
    face_landmarker = create_face_landmarker()
    metrics = FacialMetricsTracker()
    blinks = BlinkTracker(cfg.BLINK_RATE_WINDOW_SEC)
    perclos = PerclosTracker(cfg.PERCLOS_WINDOW_SEC, cfg.CAMERA_FPS)
    nods = NodTracker(cfg.NOD_THRESHOLD)
    scorer = FatigueScorer(cfg)

    audio.start()
    
    window_name = "Tesla Dashboard - Drowsiness Detection"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    frame_idx = 0
    fps_times = []
    
    last_mp_timestamp = 0
    last_alert_state = "SAFE"

    logger.info("System Online. Starting Tracking Loop.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                time.sleep(0.01)
                continue

            fh, fw = frame.shape[:2]
            frame_idx += 1
            now = time.time()
            fps_times.append(now)
            if len(fps_times) > 30: fps_times.pop(0)
            fps = len(fps_times) / (fps_times[-1] - fps_times[0] + 1e-6) if len(fps_times) > 1 else 0

            face_tracked = False

            if frame_idx % cfg.PROCESS_EVERY == 0:
                scale = cfg.PROCESS_WIDTH / float(fw)
                proc_w, proc_h = cfg.PROCESS_WIDTH, max(1, int(fh * scale))
                small = cv2.resize(frame, (proc_w, proc_h))
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                
                # Monotonically increasing TS
                ts = int(time.monotonic() * 1000)
                if ts <= last_mp_timestamp: ts = last_mp_timestamp + 1
                last_mp_timestamp = ts

                results = face_landmarker.detect_for_video(mp_image, ts)

                if results.face_landmarks:
                    lm = results.face_landmarks[0]
                    face_tracked = True
                    metrics.update(lm, fw, fh)

            # Update specialized trackers dynamically
            blinks.update(metrics.ear < metrics.dynamic_ear_threshold, now)
            perclos.update(metrics.ear < metrics.dynamic_ear_threshold)
            if face_tracked:
                nods.update(metrics.nose_y)

            # Aggregate Data
            trackers_data = {
                'ear': metrics.ear,
                'ear_threshold': metrics.dynamic_ear_threshold,
                'mar': metrics.mar,
                'perclos': perclos.value,
                'bpm': blinks.blinks_per_min,
                'is_nodding': nods.is_nodding
            }
            
            # Weighted Scoring Algorithm Execute
            state_info = scorer.evaluate(trackers_data, face_tracked)
            
            # --- Alert Triggers ---
            current_state = state_info['state']
            if current_state != "SAFE":
                if current_state != last_alert_state and cfg.SAVE_VIDEO:
                    # Save 5 sec before this happened
                    video_saver.save_clip(camera.get_buffer(), fps, fw, fh, current_state)
            last_alert_state = current_state

            # Send hardware/audio triggers
            audio.set_level(state_info['level_flag'])
            arduino.send(state_info['level_flag'])

            # Render UI
            sys_info = {'fps': fps, 'arduino': arduino._port_name if arduino.connected else 'Offline'}
            output_frame = ui.render(frame, state_info, trackers_data, sys_info)

            cv2.imshow(window_name, output_frame)

            # Exit Hooks
            if cv2.waitKey(1) & 0xFF == ord('q'): break
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1: break
            except Exception:
                break

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Initiating elegant shutdown...")
        audio.stop()
        arduino.close()
        video_saver.close()
        camera.close()
        cv2.destroyAllWindows()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()
