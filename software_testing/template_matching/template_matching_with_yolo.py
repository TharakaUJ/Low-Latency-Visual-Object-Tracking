import cv2
import numpy as np
import argparse
import sys

# Import the open-vocabulary model
try:
    from ultralytics import YOLOE
except ImportError:
    print("Warning: YOLOE not found. Ensure ultralytics is updated.")
    from ultralytics import YOLOWorld as YOLOE  # Fallback

# ==========================================
# TRACKER PARAMETERS
# ==========================================
ALPHA = 0.7                  # Weight for the original template (0.0 to 1.0)
SEARCH_RADIUS = 200           # Number of pixels to expand around the previous bounding box
CONFIDENCE_THRESHOLD = 0.60  # Minimum template combined score to update t_latest

# ==========================================
# YOLOE AI SUPERVISOR PARAMETERS
# ==========================================
PROMPT = "face"                     # Text prompt for the open-vocabulary model
MODEL_WEIGHTS = "../yoloe-26n-seg.pt"       # Nano model weights (downloads automatically)
POLL_INTERVAL = 90                 # Re-detect with AI every N frames (set to 0 to disable)
LOW_CONFIDENCE_THRESHOLD = 0.40    # Re-detect with AI if template matching score drops below this

def get_search_region(bbox, frame_w, frame_h, radius):
    x, y, w, h = bbox
    sx = max(0, x - radius)
    sy = max(0, y - radius)
    ex = min(frame_w, x + w + radius)
    ey = min(frame_h, y + h + radius)
    return sx, sy, ex, ey

def extract_template(frame, x, y, w, h):
    return frame[y:y+h, x:x+w].copy()

def get_ai_detection(model, frame, prompt):
    """Runs YOLOE and returns the highest confidence bounding box for the prompt."""
    results = model(frame, verbose=False)
    if not results or len(results[0].boxes) == 0:
        return None
    
    # Get the bounding box with the highest confidence
    boxes = results[0].boxes
    best_idx = np.argmax(boxes.conf.cpu().numpy())
    box = boxes.xyxy[best_idx].cpu().numpy()
    conf = boxes.conf[best_idx].item()
    
    x1, y1, x2, y2 = map(int, box)
    w = x2 - x1
    h = y2 - y1
    
    # Ensure valid dimensions
    if w <= 0 or h <= 0:
        return None
        
    return (x1, y1, w, h), conf

def track_frame(frame, bbox, t_original, t_latest):
    frame_h, frame_w = frame.shape[:2]
    x, y, w, h = bbox
    
    sx, sy, ex, ey = get_search_region(bbox, frame_w, frame_h, SEARCH_RADIUS)
    search_img = frame[sy:ey, sx:ex]
    
    if search_img.shape[0] < h or search_img.shape[1] < w:
        return bbox, 0.0, 0.0, 0.0
        
    res_original = cv2.matchTemplate(search_img, t_original, cv2.TM_CCOEFF_NORMED)
    res_latest = cv2.matchTemplate(search_img, t_latest, cv2.TM_CCOEFF_NORMED)
    
    combined_res = ALPHA * res_original + (1.0 - ALPHA) * res_latest
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(combined_res)
    
    best_px, best_py = max_loc
    new_x = sx + best_px
    new_y = sy + best_py
    
    score_original = res_original[best_py, best_px]
    score_latest = res_latest[best_py, best_px]
    
    return (new_x, new_y, w, h), max_val, score_original, score_latest

def main():
    parser = argparse.ArgumentParser(description="AI-Supervised Template Tracker")
    parser.add_argument("--video", type=str, help="Path to input video file")
    parser.add_argument("--camera", action="store_true", help="Use webcam")
    args = parser.parse_args()

    if args.camera:
        cap = cv2.VideoCapture(0)
    elif args.video:
        cap = cv2.VideoCapture(args.video)
    else:
        print("Error: Please specify --video <file> or --camera")
        sys.exit(1)

    # 1. Initialize the YOLOE Model
    print(f"Loading AI Model ({MODEL_WEIGHTS}) looking for '{PROMPT}'...")
    ai_model = YOLOE(MODEL_WEIGHTS)
    
    # Some Ultralytics versions require get_text_pe, others just take the list. 
    # Fallback handles API variations.
    try:
        ai_model.set_classes([PROMPT])
    except TypeError:
        ai_model.set_classes([PROMPT], ai_model.get_text_pe([PROMPT]))

    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read video.")
        sys.exit(1)

    # 2. Initial Object Selection via AI
    print(f"Searching for '{PROMPT}' in the first frame...")

    detection = None

    while detection is None:
        detection = get_ai_detection(ai_model, frame, PROMPT)
        if detection is None:
            print(f"Failed to find '{PROMPT}' in the first frame. Press 'q' to exit or any other key to retry.")
            cv2.imshow("First Frame", frame)
            key = cv2.waitKey(0) & 0xFF
            if key == ord('q'):
                cap.release()
                cv2.destroyAllWindows()
                sys.exit(1)
            else:
                ret, frame = cap.read()
                if not ret:
                    print("Error: Could not read video.")
                    sys.exit(1)
    
    # if detection is None:
    #     print(f"Failed to find '{PROMPT}' in the first frame. Exiting.")
    #     sys.exit(1)
        
    bbox, ai_conf = detection
    x, y, w, h = bbox
    print(f"Found '{PROMPT}' with {ai_conf:.2f} confidence at {bbox}")
    
    t_original = extract_template(frame, x, y, w, h)
    t_latest = t_original.copy()
    
    cv2.namedWindow("T_original", cv2.WINDOW_NORMAL)
    cv2.namedWindow("T_latest", cv2.WINDOW_NORMAL)

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        fh, fw = frame.shape[:2]

        # 3. Perform Fast Template Tracking
        new_bbox, combined_score, score_orig, score_lat = track_frame(frame, bbox, t_original, t_latest)
        nx, ny, nw, nh = new_bbox
        
        # 4. Check if AI Supervisor needs to intervene
        needs_ai = False
        ai_reason = ""
        
        if combined_score < LOW_CONFIDENCE_THRESHOLD:
            needs_ai = True
            ai_reason = "Low tracking confidence"
        elif POLL_INTERVAL > 0 and frame_count % POLL_INTERVAL == 0:
            needs_ai = True
            ai_reason = f"Periodic poll (Frame {frame_count})"
            
        status_text = ""
        box_color = (0, 255, 0) # Green for good template match
        
        if needs_ai:
            status_text = f"AI Polled: {ai_reason}"
            detection = get_ai_detection(ai_model, frame, PROMPT)
            
            if detection is not None:
                new_bbox, ai_conf = detection
                nx, ny, nw, nh = new_bbox
                
                # If AI finds it, we completely reset both templates 
                # because the object's appearance may have drastically changed.
                if nx >= 0 and ny >= 0 and nx + nw <= fw and ny + nh <= fh:
                    t_original = extract_template(frame, nx, ny, nw, nh)
                    t_latest = t_original.copy()
                    bbox = new_bbox
                    box_color = (255, 0, 255) # Magenta for AI intervention
                    status_text += f" -> Object found ({ai_conf:.2f})"
            else:
                status_text += " -> AI missed, coasting on templates"
                bbox = new_bbox
                box_color = (0, 0, 255) # Red for losing track
        else:
            # Standard Template Update Logic
            if combined_score >= CONFIDENCE_THRESHOLD:
                if nx >= 0 and ny >= 0 and nx + nw <= fw and ny + nh <= fh:
                    t_latest = extract_template(frame, nx, ny, nw, nh)
                    bbox = new_bbox
                    status_text = "Template Tracker: Normal (Updated latest)"
            else:
                bbox = new_bbox
                status_text = "Template Tracker: Normal (Coasting)"
                box_color = (0, 165, 255) # Orange for medium confidence coasting

        # ==========================================
        # VISUALIZATION
        # ==========================================
        display_frame = frame.copy()
        
        # Search Region
        sx, sy, ex, ey = get_search_region(bbox, fw, fh, SEARCH_RADIUS)
        cv2.rectangle(display_frame, (sx, sy), (ex, ey), (0, 255, 255), 1)
        
        # Bounding Box
        cv2.rectangle(display_frame, (nx, ny), (nx + nw, ny + nh), box_color, 2)
        
        # Overlay Stats
        cv2.putText(display_frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)
        if not needs_ai:
            cv2.putText(display_frame, f"Combined Score: {combined_score:.2f}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(display_frame, f"Original: {score_orig:.2f} | Latest: {score_lat:.2f}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("Tracking", display_frame)
        if t_original.size > 0: cv2.imshow("T_original", t_original)
        if t_latest.size > 0: cv2.imshow("T_latest", t_latest)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()