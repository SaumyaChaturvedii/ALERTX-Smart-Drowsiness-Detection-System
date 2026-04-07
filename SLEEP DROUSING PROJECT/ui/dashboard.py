import cv2
import numpy as np
import time
import math
from collections import deque

class DashboardUI:
    # AESTHETICS - Neon Dark Mode Colors (BGR)
    C_BG = (10, 12, 16)
    C_PANEL_BG = (20, 24, 30)         
    C_PANEL_OUTLINE = (45, 55, 75)    
    C_TEXT_PRIMARY = (245, 250, 255)
    C_TEXT_DIM = (140, 155, 175)
    
    # Futuristic state colors (BGR)
    C_SAFE = (230, 250, 70)      # Neon Blue-Cyan
    C_WARN = (0, 204, 255)       # Neon Yellow
    C_DANGER = (50, 50, 255)     # Deep Neon Red

    def __init__(self, cfg):
        self.cfg = cfg
        self.score_history = deque(maxlen=200)
        for _ in range(200): self.score_history.append(0) # pre-fill
        
        # Physics / Animation variables
        self.wave_phase = 0.0
        self.pulse_phase = 0.0
        
        # High performance cache
        self._cached_shape = None
        self._vignette_mask = None
        self._scanline_mask = None

    def _build_raster_caches(self, fh, fw):
        if self._cached_shape == (fh, fw): return
        self._cached_shape = (fh, fw)
        
        # 1. Vignette calculation
        X = np.linspace(-1, 1, fw)
        Y = np.linspace(-1, 1, fh)
        x_grid, y_grid = np.meshgrid(X, Y)
        d = np.sqrt(x_grid**2 + y_grid**2)
        vignette = 1.0 - np.clip((d - 0.45) * 1.2, 0, 1)
        self._vignette_mask = np.dstack([vignette]*3).astype(np.float32)
        
        # 2. Interlaced Scanlines
        scanlines = np.ones((fh, fw, 3), dtype=np.float32)
        scanlines[1::3, :, :] = 0.85 # Darken every 3rd line subtly
        self._scanline_mask = scanlines

    def _apply_cinematic_base(self, frame):
        fh, fw = frame.shape[:2]
        self._build_raster_caches(fh, fw)
        
        # Convert to float for fast multiply
        f_frame = frame.astype(np.float32)
        f_frame = f_frame * self._vignette_mask * self._scanline_mask
        
        # Add a subtle cold blue tint to camera feed 
        tint = np.full_like(f_frame, (40, 20, 10), dtype=np.float32) # BGR
        f_frame = cv2.addWeighted(f_frame, 0.85, tint, 0.15, 0)
        
        return np.clip(f_frame, 0, 255).astype(np.uint8)

    def _draw_text(self, img, text, pos, scale, color, thickness=1, align="left", glow=False):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
        x, y = pos
        if align == "center": x -= tw // 2
        elif align == "right": x -= tw
        
        x, y = int(x), int(y)
        
        if glow:
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, color, thickness + 4, cv2.LINE_AA)
        
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, (255,255,255) if glow else color, thickness, cv2.LINE_AA)

    def _draw_glass_panel(self, canvas, frame, rect, alpha=0.6, color=None):
        x, y, w, h = rect
        color = color or self.C_PANEL_BG
        
        # Draw on a scratch pad to avoid intersecting alphas darkening each other
        sub_canvas = canvas[y:y+h, x:x+w]
        
        # Dark base
        blended = cv2.addWeighted(sub_canvas, 1-alpha, np.full_like(sub_canvas, color), alpha, 0)
        canvas[y:y+h, x:x+w] = blended
        
        # Glowing border limits
        cv2.rectangle(canvas, (x, y), (x+w, y+h), self.C_PANEL_OUTLINE, 1)
        
        # Accent corner brackets (sci-fi tactical look)
        cl = 15 # corner length
        ct = 2  # corner thickness
        cc = self.C_TEXT_DIM
        
        # Top-Left
        cv2.line(canvas, (x, y), (x+cl, y), cc, ct)
        cv2.line(canvas, (x, y), (x, y+cl), cc, ct)
        # Top-Right
        cv2.line(canvas, (x+w, y), (x+w-cl, y), cc, ct)
        cv2.line(canvas, (x+w, y), (x+w, y+cl), cc, ct)
        # Bottom-Left
        cv2.line(canvas, (x, y+h), (x+cl, y+h), cc, ct)
        cv2.line(canvas, (x, y+h), (x, y+h-cl), cc, ct)
        # Bottom-Right
        cv2.line(canvas, (x+w, y+h), (x+w-cl, y+h), cc, ct)
        cv2.line(canvas, (x+w, y+h), (x+w, y+h-cl), cc, ct)

    def _draw_circular_progress(self, canvas, center, radius, value, max_value, color, thickness=8):
        cx, cy = center
        # Background track
        cv2.circle(canvas, (cx, cy), radius, self.C_PANEL_OUTLINE, thickness, cv2.LINE_AA)
        
        angle = (value / max_value) * 360.0
        start_angle = -90
        end_angle = start_angle + angle
        
        # Foreground track
        cv2.ellipse(canvas, (cx, cy), (radius, radius), 0, start_angle, end_angle, color, thickness, cv2.LINE_AA)
        
        # Glow track (draw over to pop)
        cv2.ellipse(canvas, (cx, cy), (radius, radius), 0, start_angle, end_angle, color, max(1, thickness-4), cv2.LINE_AA)

    def _draw_smooth_graph(self, canvas, rect, history, master_color):
        x, y, w, h = rect
        self._draw_glass_panel(canvas, canvas, rect, alpha=0.5)
        
        self._draw_text(canvas, "SYSTEM FATIGUE METRIC", (x+15, y+25), 0.4, self.C_TEXT_DIM, 1)
        
        if len(history) < 10: return
        
        # Smooth history with a moving average (simulated spline / bezier via smoothing computation)
        arr = np.array(history, dtype=np.float32)
        window = 8
        smoothed = np.convolve(arr, np.ones(window)/window, mode='valid')
        
        pts = []
        for i, val in enumerate(smoothed):
            # Normalize X across width
            px = x + 10 + int(i * (w - 20) / max(1, len(smoothed) - 1))
            val_norm = max(0, min(100, val)) / 100.0
            py = y + h - 15 - int(val_norm * (h - 50))
            pts.append([px, py])
            
        pts = np.array(pts, np.int32)
        
        # Paint the area under curve with alpha gradient trick
        base_line = np.array([[pts[-1][0], y+h-15], [pts[0][0], y+h-15]], np.int32)
        poly = np.vstack((pts, base_line))
        
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [poly], master_color)
        cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas) # Soft transparent fill
        
        # Core curve line
        cv2.polylines(canvas, [pts], False, master_color, 2, cv2.LINE_AA)

    def _draw_iron_man_center(self, canvas, frame_shape, state_info, color):
        fh, fw = frame_shape
        cx, cy = fw // 2, fh // 2
        
        # Bounding box sizing for the reticle
        r_inner = 180
        r_outer = 210
        
        # Rotating outer ring dashes
        self.pulse_phase += 0.05
        
        # Inner Status
        score = state_info['score']
        self._draw_circular_progress(canvas, (cx, cy), r_inner, score, 100, color, thickness=6)
        
        # Draw dynamic center text
        # Glow the text if warning or higher
        txt = f"{score:.0f}"
        self._draw_text(canvas, txt, (cx, cy + 15), 1.8, color, 3, align="center", glow=(score > 20))
        self._draw_text(canvas, "SYSTEM SCORE", (cx, cy + 50), 0.5, self.C_TEXT_DIM, 1, align="center")
        
        # Rotating outer tactical arcs
        num_arcs = 4
        arc_len = 45
        for i in range(num_arcs):
            start = i * (360/num_arcs) + math.degrees(self.pulse_phase)
            cv2.ellipse(canvas, (cx, cy), (r_outer, r_outer), 0, start, start+arc_len, self.C_PANEL_OUTLINE, 2, cv2.LINE_AA)

    def _draw_alert_banner(self, canvas, frame_shape, state_info, color):
        fh, fw = frame_shape
        level = state_info['state']
        
        # Only draw aggressive banner on HIGH alert
        if level in ["SAFE"]: return
        
        # Pulsing opacity
        pulse = (math.sin(self.wave_phase * 4) + 1.0) / 2.0  # 0 to 1
        alpha = 0.4 + (0.4 * pulse)
        
        h = 70
        yw = fh - h - 30
        
        poly = np.array([
            [40, yw + h],
            [70, yw],
            [fw - 70, yw],
            [fw - 40, yw + h]
        ], np.int32)
        
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [poly], color)
        cv2.addWeighted(overlay, alpha, canvas, 1 - alpha, 0, canvas)
        
        # Edges
        cv2.polylines(canvas, [poly], True, color, 2, cv2.LINE_AA)
        
        msg = f"WARNING: {level} FATIGUE DETECTED"
        if level == "FACE_LOST": msg = "CRITICAL: FACE TRACKING LOST"
        elif level == "SLEEP": msg = "CRITICAL: ACTIVE SLEEP DETECTED"
        
        self._draw_text(canvas, msg, (fw // 2, yw + 45), 0.9, (255,255,255), 2, align="center", glow=True)

    def render(self, frame, state_info, trackers, sys_info):
        fh, fw = frame.shape[:2]
        self.score_history.append(state_info['score'])
        self.wave_phase += 0.1

        # 1. Base Layer: Cinematic Effects
        base = self._apply_cinematic_base(frame)
        canvas = base.copy() 
        
        # 2. State Resolution
        level = state_info['state']
        if level == "SAFE": color = self.C_SAFE
        elif level == "WARNING": color = self.C_WARN
        else: color = self.C_DANGER

        # 3. Left Panel (Data Metrics - 22% width)
        lw = int(fw * 0.22)
        panel_y = 40
        panel_h = fh - 80
        self._draw_glass_panel(canvas, base, (30, panel_y, lw, panel_h), alpha=0.6)
        
        self._draw_text(canvas, "TELEMETRY", (50, panel_y + 40), 0.7, self.C_TEXT_PRIMARY, 2, glow=True)
        cv2.line(canvas, (50, panel_y + 55), (30 + lw - 20, panel_y + 55), self.C_PANEL_OUTLINE, 2)
        
        # Metrics Mapping
        y_off = panel_y + 100
        metrics = [
            ("EAR", f"{trackers['ear']:.3f}", trackers['ear'] < trackers['ear_threshold']),
            ("MAR", f"{trackers['mar']:.3f}", trackers['mar'] > self.cfg.MAR_THRESHOLD),
            ("PERCLOS", f"{trackers['perclos']*100:.0f}%", trackers['perclos'] > self.cfg.PERCLOS_ALERT_LEVEL),
            ("BPM", f"{trackers['bpm']}", trackers['bpm'] > 25),
            ("NOD STAT", "ACTIVE" if trackers['is_nodding'] else "STEADY", trackers['is_nodding'])
        ]
        
        for k, v, is_bad in metrics:
            self._draw_text(canvas, k, (50, y_off), 0.6, self.C_TEXT_DIM, 1)
            c = self.C_DANGER if is_bad else self.C_SAFE
            self._draw_text(canvas, v, (30 + lw - 20, y_off), 0.6, c, 1, align="right", glow=is_bad)
            y_off += 60

        # Detailed info box
        self._draw_text(canvas, "CLOSURE TIME", (50, y_off + 30), 0.5, self.C_TEXT_DIM, 1)
        self._draw_text(canvas, f"{state_info['eyes_closed_dur']:.1f} sec", (30 + lw - 20, y_off + 30), 0.5, self.C_TEXT_PRIMARY, 1, align="right")

        # 4. Top Right (Smooth Graph)
        gw = int(fw * 0.3)
        self._draw_smooth_graph(canvas, (fw - gw - 30, 40, gw, 160), self.score_history, color)

        # 5. Center (Iron Man Reticle Focus)
        self._draw_iron_man_center(canvas, (fh, fw), state_info, color)
        
        # 6. Bottom (Dynamic Alert Banner)
        self._draw_alert_banner(canvas, (fh, fw), state_info, color)

        # 7. Mini System Status (Bottom Right)
        sys_y = fh - 60
        self._draw_text(canvas, f"FPS: {sys_info['fps']:.1f}", (fw - 140, sys_y), 0.4, self.C_TEXT_DIM)
        c_ard = self.C_SAFE if sys_info['arduino'] != 'Offline' else self.C_DANGER
        self._draw_text(canvas, f"MCU: {sys_info['arduino']}", (fw - 140, sys_y + 25), 0.4, c_ard)

        return canvas
