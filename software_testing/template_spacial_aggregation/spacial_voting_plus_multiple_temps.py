import cv2
import numpy as np

# --- Configuration ---
T_SIZE = 16
ROI_SIZE = 64
STRIDE = 4
TOP_N = 5

# Spatial voting 3x3 kernel
VOTE_KERNEL = np.array([[1, 2, 1], 
                        [2, 3, 2], 
                        [1, 2, 1]], dtype=np.float32)
VOTE_KERNEL /= np.sum(VOTE_KERNEL)

# Define offsets for 8 templates (3x3 grid, skipping the center)
# These are the top-left coordinates of each 16x16 template relative to the 64x64 bounding box
TEMPLATE_OFFSETS = [
    (0, 0),   (24, 0),   (48, 0),
    (0, 24),             (48, 24),
    (0, 48),  (24, 48),  (48, 48)
]

# Globals
templates = []
frame_gray = None

def select_template(event, x, y, flags, param):
    global templates, frame_gray
    if event == cv2.EVENT_LBUTTONDOWN:
        # Define the top-left of the 64x64 area based on where the user clicked
        x1, y1 = max(0, x - ROI_SIZE//2), max(0, y - ROI_SIZE//2)
        
        # Ensure it doesn't go out of bounds
        if x1 + ROI_SIZE <= frame_gray.shape[1] and y1 + ROI_SIZE <= frame_gray.shape[0]:
            templates.clear()
            # Extract the 8 sub-templates
            for ox, oy in TEMPLATE_OFFSETS:
                tx, ty = x1 + ox, y1 + oy
                templates.append(frame_gray[ty:ty+T_SIZE, tx:tx+T_SIZE].copy())
            print("8 Templates captured! Tracking started.")

def shift_grid(grid, shift_x, shift_y):
    """Shifts a 2D grid by integer amounts. Simulates address offsets in FPGA BRAM."""
    h, w = grid.shape
    shifted = np.zeros_like(grid)
    
    src_y1, src_y2 = max(0, -shift_y), min(h, h - shift_y)
    src_x1, src_x2 = max(0, -shift_x), min(w, w - shift_x)
    
    dst_y1, dst_y2 = max(0, shift_y), min(h, h + shift_y)
    dst_x1, dst_x2 = max(0, shift_x), min(w, w + shift_x)
    
    if src_y1 < src_y2 and src_x1 < src_x2:
        shifted[dst_y1:dst_y2, dst_x1:dst_x2] = grid[src_y1:src_y2, src_x1:src_x2]
    return shifted

def main():
    global frame_gray, templates
    
    cap = cv2.VideoCapture(0)
    
    main_window = "Multi-Template Tracker (Click to select target)"
    heat_window = "Accumulated Heatmap (8 Templates)"
    
    cv2.namedWindow(main_window)
    cv2.namedWindow(heat_window)
    cv2.setMouseCallback(main_window, select_template)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if len(templates) == 8:
            master_grid = None
            
            # 1. Evaluate all 8 templates and accumulate them on the discrete grid
            for idx, tmpl in enumerate(templates):
                # Standard matching
                diff_map = cv2.matchTemplate(frame_gray, tmpl, cv2.TM_SQDIFF_NORMED)
                score_map = 1.0 - diff_map # Convert to "Higher is Better"
                
                # Downsample to hardware stride constraint
                grid_scores = score_map[::STRIDE, ::STRIDE]
                
                # Shift the score map so the peak aligns with the Top-Left of the 64x64 object box
                ox, oy = TEMPLATE_OFFSETS[idx]
                shifted_scores = shift_grid(grid_scores, -ox // STRIDE, -oy // STRIDE)
                
                # Accumulate scores
                if master_grid is None:
                    master_grid = shifted_scores
                else:
                    master_grid += shifted_scores
            
            # Normalize master grid for thresholding/display (average of 8)
            master_grid /= 8.0
            
            # --- A. BASELINE METHOD (Argmax on raw discrete grid) ---
            _, _, _, max_loc = cv2.minMaxLoc(master_grid)
            base_x = max_loc[0] * STRIDE
            base_y = max_loc[1] * STRIDE
            
            # --- B. SPATIAL VOTING METHOD (Argmax on convolved discrete grid) ---
            voted_grid = cv2.filter2D(master_grid, -1, VOTE_KERNEL)
            _, _, _, max_voted_loc = cv2.minMaxLoc(voted_grid)
            vote_x = max_voted_loc[0] * STRIDE
            vote_y = max_voted_loc[1] * STRIDE

            # --- C. TOP-N METHOD (Weighted centroid of top N on raw grid) ---
            flat_indices = np.argpartition(master_grid.flatten(), -TOP_N)[-TOP_N:]
            top_y_grid, top_x_grid = np.unravel_index(flat_indices, master_grid.shape)
            top_scores = master_grid[top_y_grid, top_x_grid]
            
            weight_sum = np.sum(top_scores)
            if weight_sum > 0:
                topn_x = np.sum(top_x_grid * STRIDE * top_scores) / weight_sum
                topn_y = np.sum(top_y_grid * STRIDE * top_scores) / weight_sum
            else:
                topn_x, topn_y = base_x, base_y

            # --- VISUALIZATION: MAIN FRAME ---
            
            # Draw Baseline (Red discrete box, 64x64)
            cv2.rectangle(frame, (base_x, base_y), (base_x + ROI_SIZE, base_y + ROI_SIZE), (0, 0, 255), 2)
            
            # Draw Voting (Blue discrete box)
            cv2.rectangle(frame, (vote_x-1, vote_y-1), (vote_x + ROI_SIZE+1, vote_y + ROI_SIZE+1), (255, 0, 0), 2)
            
            # Draw Top-N (Green smooth circle at the center of the 64x64 patch)
            center_x = int(topn_x + ROI_SIZE/2)
            center_y = int(topn_y + ROI_SIZE/2)
            cv2.circle(frame, (center_x, center_y), 4, (0, 255, 0), -1)
            cv2.circle(frame, (center_x, center_y), ROI_SIZE//2, (0, 255, 0), 2)

            # Legend
            cv2.putText(frame, "Red Box: Baseline", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame, "Blue Box: Voting", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
            cv2.putText(frame, "Green Circle: Top-N", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Create a 64x64 preview showing the 8 templates layout
            preview = np.zeros((ROI_SIZE, ROI_SIZE), dtype=np.uint8)
            for idx, tmpl in enumerate(templates):
                ox, oy = TEMPLATE_OFFSETS[idx]
                preview[oy:oy+T_SIZE, ox:ox+T_SIZE] = tmpl
            preview_bgr = cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)
            frame[90:90+ROI_SIZE, 10:10+ROI_SIZE] = preview_bgr
            cv2.putText(frame, "8x Templates", (10, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # --- VISUALIZATION: HEATMAP ---
            # Normalize voted grid to 0-255 for visualization
            heatmap_norm = cv2.normalize(voted_grid, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            heatmap_color = cv2.applyColorMap(heatmap_norm, cv2.COLORMAP_JET)
            
            # Resize using nearest neighbor to clearly show the discrete grid blocks
            heatmap_resized = cv2.resize(heatmap_color, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
            
            # Draw crosshairs on the heatmap corresponding to the Top-N result
            cv2.line(heatmap_resized, (center_x, 0), (center_x, frame.shape[0]), (255, 255, 255), 1)
            cv2.line(heatmap_resized, (0, center_y), (frame.shape[1], center_y), (255, 255, 255), 1)
            cv2.putText(heatmap_resized, "Crosshair: Top-N Centroid", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(heat_window, heatmap_resized)
            
        else:
            cv2.putText(frame, "Click anywhere to select a 64x64 target area", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow(main_window, frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()