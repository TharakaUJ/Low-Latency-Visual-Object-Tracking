import cv2
import numpy as np
import csv
import math
import time

# ====================================================================
# CONFIGURATION & PARAMETERS
# ====================================================================
class Config:
    TEMPLATE_SIZE = 16
    SEARCH_RADIUS = 32         # How far to look around the previous position
    MAX_TEMP_TEMPLATES = 3     # Fixed history size
    SPATIAL_RADIUS = 6         # Radius for spatial aggregation (Kernel size = 2*R + 1)
    
    # Toggle to simulate SAD (Sum of Absolute Differences) which is FPGA friendly. 
    # If False, uses NCC (Normalized Cross Correlation).
    USE_SAD = True  
    
    # These are linked to the UI Trackbars
    UPDATE_THRESHOLD = 0.50    # Score required to extract a new template
    W_ORIGINAL = 0.8           # Weight of the original template
    W_TEMPORARY = 0.2          # Weight of the temporary templates
    
    JUMP_LIMIT = 15            # Max pixels the target can move before we refuse to update (sanity check)

# ====================================================================
# TRACKER CLASS (Classical Streaming-Friendly Architecture)
# ====================================================================
class StreamingTracker:
    def __init__(self, name, use_adaptive, use_spatial, color):
        self.name = name
        self.use_adaptive = use_adaptive
        self.use_spatial = use_spatial
        self.color = color
        
        self.t_orig = None
        self.t_temps = []
        self.pos = (0, 0)
        self.score = 0.0
        self.is_initialized = False
        
        # History for metrics
        self.history_pos = []
        self.history_scores = []
        self.update_count = 0
        self.lost_track_count = 0
        self.last_update_flag = False
        
        # For visualization
        self.latest_score_map = None

    def initialize(self, frame_gray, center_x, center_y, initial_patch):
        self.t_orig = cv2.resize(initial_patch, (Config.TEMPLATE_SIZE, Config.TEMPLATE_SIZE))
        self.pos = (center_x, center_y)
        self.t_temps = []
        self.is_initialized = True
        
        self.history_pos = [self.pos]
        self.history_scores = [1.0]
        self.update_count = 0
        self.lost_track_count = 0

    def match_patch(self, search_window, template):
        """Matches a template and returns a score map. Normalizes SAD to behave like NCC (higher is better)."""
        if Config.USE_SAD:
            res = cv2.matchTemplate(search_window, template, cv2.TM_SQDIFF_NORMED)
            return 1.0 - res # Invert so higher is better (0.0 to 1.0)
        else:
            res = cv2.matchTemplate(search_window, template, cv2.TM_CCOEFF_NORMED)
            return np.clip(res, 0.0, 1.0) # Clip negative correlations

    def update(self, frame_gray):
        if not self.is_initialized:
            return
            
        cx, cy = self.pos
        T = Config.TEMPLATE_SIZE
        R = Config.SEARCH_RADIUS
        
        # 1. Define bounds and extract search window safely
        h, w = frame_gray.shape
        x1 = max(0, cx - R - T//2)
        y1 = max(0, cy - R - T//2)
        x2 = min(w, cx + R + T//2)
        y2 = min(h, cy + R + T//2)
        
        search_window = frame_gray[y1:y2, x1:x2]
        if search_window.shape[0] < T or search_window.shape[1] < T:
            self.lost_track_count += 1
            return # Near edge, skip
            
        # 2. Template Matching
        # Original template score
        score_map_orig = self.match_patch(search_window, self.t_orig)
        
        # Temporary templates score
        score_map_temps = None
        if self.use_adaptive and len(self.t_temps) > 0:
            temp_maps = [self.match_patch(search_window, t) for t in self.t_temps]
            score_map_temps = np.max(temp_maps, axis=0) # Best temporary score per pixel
            
        # 3. Combine Evidence
        if score_map_temps is not None:
            combined_map = (Config.W_ORIGINAL * score_map_orig) + (Config.W_TEMPORARY * score_map_temps)
        else:
            combined_map = score_map_orig

        # 4. Spatial Aggregation (Local confidence spreading)
        if self.use_spatial:
            k = Config.SPATIAL_RADIUS * 2 + 1
            # A box filter acts as a 2D moving average. 
            # In an FPGA, this is a line buffer + accumulator.
            combined_map = cv2.boxFilter(combined_map, -1, (k, k))
            
        self.latest_score_map = combined_map

        # 5. Find strongest location
        _, max_val, _, max_loc = cv2.minMaxLoc(combined_map)
        self.score = max_val
        
        # Calculate new absolute center position
        new_cx = x1 + max_loc[0] + T//2
        new_cy = y1 + max_loc[1] + T//2
        
        # Jump distance calculation
        jump = math.hypot(new_cx - cx, new_cy - cy)
        self.pos = (new_cx, new_cy)
        
        # Track stats
        self.history_pos.append(self.pos)
        self.history_scores.append(self.score)
        if self.score < 0.3:
            self.lost_track_count += 1

        # 6. Conservative Template Update (Adaptive only)
        self.last_update_flag = False
        if self.use_adaptive:
            # Check thresholds: score is good AND it didn't teleport (jump limit)
            if self.score > Config.UPDATE_THRESHOLD and jump < Config.JUMP_LIMIT:
                # Extract new patch safely
                px1, py1 = new_cx - T//2, new_cy - T//2
                px2, py2 = px1 + T, py1 + T
                if px1 >= 0 and py1 >= 0 and px2 <= w and py2 <= h:
                    new_patch = frame_gray[py1:py2, px1:px2].copy()
                    
                    self.t_temps.append(new_patch)
                    if len(self.t_temps) > Config.MAX_TEMP_TEMPLATES:
                        self.t_temps.pop(0) # Remove oldest (FIFO)
                        
                    self.last_update_flag = True
                    self.update_count += 1

# ====================================================================
# UI CALLBACKS & MAIN LOOP
# ====================================================================
drawing = False
roi_pts = []

def mouse_callback(event, x, y, flags, param):
    global drawing, roi_pts
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        roi_pts = [(x, y)]
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        roi_pts.append((x, y))

def on_trackbar(val):
    pass # Trackbars read values directly in the loop

def main():
    global roi_pts

    cap = cv2.VideoCapture(0)
    
    cv2.namedWindow('Tracker Testbed')
    cv2.setMouseCallback('Tracker Testbed', mouse_callback)
    
    cv2.namedWindow('Controls')
    cv2.resizeWindow('Controls', 400, 200)
    cv2.createTrackbar('Thresh (%)', 'Controls', int(Config.UPDATE_THRESHOLD * 100), 100, on_trackbar)
    cv2.createTrackbar('W_Orig (%)', 'Controls', int(Config.W_ORIGINAL * 100), 100, on_trackbar)
    cv2.createTrackbar('W_Temp (%)', 'Controls', int(Config.W_TEMPORARY * 100), 100, on_trackbar)
    
    # Initialize our three trackers
    trackers = [
        StreamingTracker("A. Baseline", use_adaptive=False, use_spatial=False, color=(0, 0, 255)),     # Red
        StreamingTracker("B. Adaptive", use_adaptive=True, use_spatial=False, color=(0, 255, 0)),      # Green
        StreamingTracker("C. Spatial Agg", use_adaptive=True, use_spatial=True, color=(255, 0, 0))     # Blue
    ]
    
    initialized = False
    frame_num = 0
    csv_data = []

    print("--- Tracker Testbed Started ---")
    print("1. Drag a box over the target to initialize.")
    print("2. Press 'r' to reset and select a new target.")
    print("3. Press 'q' to quit and generate metrics.\n")

    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        display = frame.copy()
        
        # Read UI Controls
        Config.UPDATE_THRESHOLD = cv2.getTrackbarPos('Thresh (%)', 'Controls') / 100.0
        w_o = cv2.getTrackbarPos('W_Orig (%)', 'Controls') / 100.0
        w_t = cv2.getTrackbarPos('W_Temp (%)', 'Controls') / 100.0
        # Normalize weights so they equal 1.0
        if w_o + w_t > 0:
            Config.W_ORIGINAL = w_o / (w_o + w_t)
            Config.W_TEMPORARY = w_t / (w_o + w_t)

        if not initialized:
            if len(roi_pts) == 2:
                x1, y1 = roi_pts[0]
                x2, y2 = roi_pts[1]
                x, y = min(x1, x2), min(y1, y2)
                w, h = abs(x2 - x1), abs(y2 - y1)
                
                if w > 5 and h > 5:
                    initial_patch = frame_gray[y:y+h, x:x+w]
                    cx, cy = x + w//2, y + h//2
                    for t in trackers:
                        t.initialize(frame_gray, cx, cy, initial_patch)
                    initialized = True
                    roi_pts = []
            elif len(roi_pts) == 1:
                cv2.rectangle(display, roi_pts[0], (roi_pts[0][0]+16, roi_pts[0][1]+16), (255,255,0), 1)
                
            cv2.putText(display, "Drag mouse to select target", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
        else:
            frame_num += 1
            t0 = time.time()
            
            row_data = {"frame": frame_num}
            
            y_offset = 30
            for t in trackers:
                t.update(frame_gray)
                
                # Draw Box
                cx, cy = t.pos
                half = Config.TEMPLATE_SIZE // 2
                cv2.rectangle(display, (cx - half, cy - half), (cx + half, cy + half), t.color, 2)
                
                # Draw Stats Text
                status = "OK" if t.score > 0.4 else "LOST"
                update_str = "*" if t.last_update_flag else ""
                txt = f"{t.name}: {t.score:.2f} | Temps: {len(t.t_temps)} {update_str} [{status}]"
                cv2.putText(display, txt, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, t.color, 2)
                y_offset += 25
                
                # Save data for CSV
                row_data[f"{t.name}_x"] = cx
                row_data[f"{t.name}_y"] = cy
                row_data[f"{t.name}_score"] = t.score
                row_data[f"{t.name}_temps"] = len(t.t_temps)
                row_data[f"{t.name}_updated"] = int(t.last_update_flag)
                
            csv_data.append(row_data)
            
            # FPS Calculation
            fps = 1.0 / (time.time() - t0 + 0.00001)
            cv2.putText(display, f"FPS: {fps:.1f}", (10, y_offset + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Debug Visualizations
            # 1. Show templates of Method C (Most complex)
            t_c = trackers[2]
            debug_h, debug_w = 120, 300
            debug_panel = np.zeros((debug_h, debug_w), dtype=np.uint8)
            
            if t_c.t_orig is not None:
                # Scale up original
                big_orig = cv2.resize(t_c.t_orig, (64, 64), interpolation=cv2.INTER_NEAREST)
                debug_panel[10:74, 10:74] = big_orig
                cv2.putText(debug_panel, "Orig", (20, 95), cv2.FONT_HERSHEY_PLAIN, 1, 255, 1)
                
                # Scale up temps
                for i, tmp in enumerate(t_c.t_temps):
                    big_tmp = cv2.resize(tmp, (32, 32), interpolation=cv2.INTER_NEAREST)
                    debug_panel[10:42, 90 + i*40 : 122 + i*40] = big_tmp
                    
            cv2.imshow('Templates (Method C)', debug_panel)
            
            # 2. Show Spatial Confidence Map (Method C)
            if t_c.latest_score_map is not None:
                # Normalize score map to 0-255 for visualization
                map_norm = cv2.normalize(t_c.latest_score_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                map_color = cv2.applyColorMap(map_norm, cv2.COLORMAP_JET)
                map_resized = cv2.resize(map_color, (200, 200), interpolation=cv2.INTER_NEAREST)
                cv2.imshow('Spatial Map (Method C)', map_resized)

        cv2.imshow('Tracker Testbed', display)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            initialized = False
            roi_pts = []

    cap.release()
    cv2.destroyAllWindows()
    
    # ====================================================================
    # QUANTITATIVE METRICS OUTPUT
    # ====================================================================
    if frame_num > 0:
        print("\n--- TRACKING METRICS SUMMARY ---")
        
        with open('tracking_data.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=csv_data[0].keys())
            writer.writeheader()
            writer.writerows(csv_data)
        print("Raw data saved to tracking_data.csv")
        
        for t in trackers:
            pts = t.history_pos
            # Calculate Jitter (Average distance between consecutive frames)
            jitter = np.mean([math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]) for i in range(1, len(pts))]) if len(pts) > 1 else 0
            
            # Max Jump
            max_jump = np.max([math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]) for i in range(1, len(pts))]) if len(pts) > 1 else 0
            
            print(f"\n{t.name}:")
            print(f"  Updates (new temps): {t.update_count}")
            print(f"  Frames Lost Track:   {t.lost_track_count}")
            print(f"  Avg Jitter (px/f):   {jitter:.2f}")
            print(f"  Max Jump (px):       {max_jump:.2f}")

if __name__ == '__main__':
    main()