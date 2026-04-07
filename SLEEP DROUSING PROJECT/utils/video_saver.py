import cv2
import threading
import queue
import time
import os

class AsyncVideoSaver:
    def __init__(self, cfg):
        self.cfg = cfg
        self.save_queue = queue.Queue(maxsize=5)
        self._stop_event = threading.Event()
        
        if self.cfg.SAVE_VIDEO:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()
            
    def save_clip(self, frames, fps, width, height, event_type):
        if not self.cfg.SAVE_VIDEO or len(frames) == 0:
            return
            
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{event_type}_{timestamp}.mp4"
        filepath = os.path.join(self.cfg.VIDEO_DIR, filename)
        
        try:
            self.save_queue.put_nowait((filepath, frames, fps, width, height))
        except queue.Full:
            pass # Drop clip if queue is full

    def _worker_loop(self):
        while not self._stop_event.is_set() or not self.save_queue.empty():
            try:
                filepath, frames, fps, w, h = self.save_queue.get(timeout=0.5)
            except queue.Empty:
                continue
                
            try:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(filepath, fourcc, max(15, fps), (w, h))
                for frame in frames:
                    out.write(frame)
                out.release()
            except Exception as e:
                pass
            finally:
                self.save_queue.task_done()

    def close(self):
        self._stop_event.set()
        if hasattr(self, '_worker'):
            try:
                self.save_queue.join()
                self._worker.join(timeout=2.0)
            except Exception:
                pass
