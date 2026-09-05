import cv2
import numpy as np
import argparse
import sys

# ==========================================
# EXPERIMENTAL PARAMETERS
# ==========================================
ALPHA = 0.75                  # Weight for the original template (0.0 to 1.0)
SEARCH_RADIUS = 100           # Number of pixels to expand around the previous bounding box
CONFIDENCE_THRESHOLD = 0.55  # Minimum combined score to update the latest template

def get_search_region(bbox, frame_w, frame_h, radius):
    """Calculates the expanded search region boundaries, ensuring they stay within the frame."""
    x, y, w, h = bbox
    sx = max(0, x - radius)
    sy = max(0, y - radius)
    ex = min(frame_w, x + w + radius)
    ey = min(frame_h, y + h + radius)
    return sx, sy, ex, ey

def extract_template(frame, x, y, w, h):
    """Safely extracts a template from the frame."""
    return frame[y:y+h, x:x+w].copy()

def track_frame(frame, bbox, t_original, t_latest):
    """
    Finds the object in the current frame within a local search region
    using a weighted combination of two templates.
    """
    frame_h, frame_w = frame.shape[:2]
    x, y, w, h = bbox
    
    # 1. Define and extract the search region
    sx, sy, ex, ey = get_search_region(bbox, frame_w, frame_h, SEARCH_RADIUS)
    search_img = frame[sy:ey, sx:ex]
    
    # Safety check: if search region is smaller than template, tracking fails
    if search_img.shape[0] < h or search_img.shape[1] < w:
        return bbox, 0.0, 0.0, 0.0
        
    # 2. Calculate similarity for both templates
    # TM_CCOEFF_NORMED returns values between -1.0 and 1.0 (1.0 is perfect match)
    res_original = cv2.matchTemplate(search_img, t_original, cv2.TM_CCOEFF_NORMED)
    res_latest = cv2.matchTemplate(search_img, t_latest, cv2.TM_CCOEFF_NORMED)
    
    # 3. Combine scores
    combined_res = ALPHA * res_original + (1.0 - ALPHA) * res_latest
    
    # 4. Find the best match location
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(combined_res)
    
    # max_loc is (x, y) inside the search_img. Convert back to global frame coordinates.
    best_px, best_py = max_loc
    new_x = sx + best_px
    new_y = sy + best_py
    
    # Extract the individual scores at the best location for reporting
    score_original = res_original[best_py, best_px]
    score_latest = res_latest[best_py, best_px]
    
    new_bbox = (new_x, new_y, w, h)
    
    return new_bbox, max_val, score_original, score_latest

def main():
    parser = argparse.ArgumentParser(description="Two-Template Object Tracker")
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

    if not cap.isOpened():
        print("Error: Could not open video source.")
        sys.exit(1)

    # Read the first frame
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame.")
        sys.exit(1)

    print("Please select the object to track. Press SPACE or ENTER to confirm, C to cancel.")
    bbox = cv2.selectROI("Tracking", frame, fromCenter=False, showCrosshair=True)
    
    # Check if selection was canceled
    if bbox[2] == 0 or bbox[3] == 0:
        print("Selection canceled. Exiting.")
        sys.exit(0)

    x, y, w, h = bbox
    
    # Initialize templates
    t_original = extract_template(frame, x, y, w, h)
    t_latest = t_original.copy()
    
    # Create windows for template visualization
    cv2.namedWindow("T_original", cv2.WINDOW_NORMAL)
    cv2.namedWindow("T_latest", cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Track the object in the current frame
        new_bbox, combined_score, score_orig, score_lat = track_frame(frame, bbox, t_original, t_latest)
        nx, ny, nw, nh = new_bbox
        
        # Determine if we should update T_latest
        updated = False
        if combined_score >= CONFIDENCE_THRESHOLD:
            # Ensure the new bounding box is fully inside the frame before extracting
            fh, fw = frame.shape[:2]
            if nx >= 0 and ny >= 0 and nx + nw <= fw and ny + nh <= fh:
                t_latest = extract_template(frame, nx, ny, nw, nh)
                bbox = new_bbox  # Update location
                updated = True
        else:
            # If confidence is too low, we still update the location to the best guess,
            # but we do NOT update the template (prevents learning background noise).
            bbox = new_bbox

        # ==========================================
        # VISUALIZATION
        # ==========================================
        display_frame = frame.copy()
        
        # Draw search region (Yellow)
        sx, sy, ex, ey = get_search_region(bbox, display_frame.shape[1], display_frame.shape[0], SEARCH_RADIUS)
        cv2.rectangle(display_frame, (sx, sy), (ex, ey), (0, 255, 255), 1)
        cv2.putText(display_frame, "Search Region", (sx, sy - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        
        # Draw bounding box (Green if high confidence, Red if low)
        box_color = (0, 255, 0) if combined_score >= CONFIDENCE_THRESHOLD else (0, 0, 255)
        cv2.rectangle(display_frame, (nx, ny), (nx + nw, ny + nh), box_color, 2)
        
        # Overlay statistics
        cv2.putText(display_frame, f"Combined Score: {combined_score:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display_frame, f"Original Score: {score_orig:.2f}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display_frame, f"Latest Score:   {score_lat:.2f}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        update_text = "Template Updated: YES" if updated else "Template Updated: NO"
        cv2.putText(display_frame, update_text, (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)

        # Show frames
        cv2.imshow("Tracking", display_frame)
        cv2.imshow("T_original", t_original)
        cv2.imshow("T_latest", t_latest)

        # Press 'q' to quit
        if cv2.waitKey(30) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()