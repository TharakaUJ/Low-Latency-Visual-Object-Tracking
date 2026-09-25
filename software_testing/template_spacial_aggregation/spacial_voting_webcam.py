import cv2
import numpy as np

# --- Configuration matching your hardware constraints ---
T_SIZE = 16
STRIDE = 4
TOP_N = 5

# Spatial voting 3x3 kernel (normalized)
VOTE_KERNEL = np.array([[1, 2, 1], 
                        [2, 4, 2], 
                        [1, 2, 1]], dtype=np.float32)
VOTE_KERNEL /= np.sum(VOTE_KERNEL)

# Globals for template selection
template = None
frame_gray = None

def select_template(event, x, y, flags, param):
    global template, frame_gray
    if event == cv2.EVENT_LBUTTONDOWN:
        # Extract a 16x16 patch centered around the mouse click
        x1, y1 = max(0, x - T_SIZE//2), max(0, y - T_SIZE//2)
        x2, y2 = x1 + T_SIZE, y1 + T_SIZE
        
        # Ensure it doesn't go out of bounds
        if x2 <= frame_gray.shape[1] and y2 <= frame_gray.shape[0]:
            template = frame_gray[y1:y2, x1:x2].copy()
            print("Template captured! Tracking started.")

def main():
    global frame_gray, template
    
    cap = cv2.VideoCapture(0)
    
    main_window = "Tracker (Click to select target)"
    heat_window = "Spatial Voting Heatmap (Discrete Grid)"
    
    cv2.namedWindow(main_window)
    cv2.namedWindow(heat_window)
    cv2.setMouseCallback(main_window, select_template)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if template is not None:
            # 1. Compute full similarity map 
            diff_map = cv2.matchTemplate(frame_gray, template, cv2.TM_SQDIFF_NORMED)
            score_map = 1.0 - diff_map # Convert to "Higher is Better"
            
            # 2. Enforce the discrete stride constraint (Simulating FPGA grid)
            grid_scores = score_map[::STRIDE, ::STRIDE]
            
            # --- A. BASELINE METHOD (Argmax on raw discrete grid) ---
            _, _, _, max_loc = cv2.minMaxLoc(grid_scores)
            base_x = max_loc[0] * STRIDE
            base_y = max_loc[1] * STRIDE
            
            # --- B. SPATIAL VOTING METHOD (Argmax on convolved discrete grid) ---
            voted_grid = cv2.filter2D(grid_scores, -1, VOTE_KERNEL)
            _, _, _, max_voted_loc = cv2.minMaxLoc(voted_grid)
            vote_x = max_voted_loc[0] * STRIDE
            vote_y = max_voted_loc[1] * STRIDE

            # --- C. TOP-N METHOD (Weighted centroid of top N on raw grid) ---
            flat_indices = np.argpartition(grid_scores.flatten(), -TOP_N)[-TOP_N:]
            top_y_grid, top_x_grid = np.unravel_index(flat_indices, grid_scores.shape)
            top_scores = grid_scores[top_y_grid, top_x_grid]
            
            weight_sum = np.sum(top_scores)
            if weight_sum > 0:
                topn_x = np.sum(top_x_grid * STRIDE * top_scores) / weight_sum
                topn_y = np.sum(top_y_grid * STRIDE * top_scores) / weight_sum
            else:
                topn_x, topn_y = base_x, base_y

            # --- VISUALIZATION: MAIN FRAME ---
            
            # Draw Baseline (Red discrete box)
            cv2.rectangle(frame, (base_x, base_y), (base_x + T_SIZE, base_y + T_SIZE), (0, 0, 255), 2)
            
            # Draw Voting (Blue discrete box, slightly offset so they don't perfectly overlap if identical)
            cv2.rectangle(frame, (vote_x-1, vote_y-1), (vote_x + T_SIZE+1, vote_y + T_SIZE+1), (255, 0, 0), 2)
            
            # Draw Top-N (Green smooth circle at the center of the patch)
            center_x = int(topn_x + T_SIZE/2)
            center_y = int(topn_y + T_SIZE/2)
            cv2.circle(frame, (center_x, center_y), 4, (0, 255, 0), -1)
            cv2.circle(frame, (center_x, center_y), 12, (0, 255, 0), 2)

            # Legend & Target Preview
            cv2.putText(frame, "Red Box: Baseline", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame, "Blue Box: Voting", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
            cv2.putText(frame, "Green Circle: Top-N", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            template_preview = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
            template_preview = cv2.resize(template_preview, (64, 64))
            frame[90:154, 10:74] = template_preview
            cv2.putText(frame, "Target", (10, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

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
            cv2.putText(frame, "Click anywhere to select a 16x16 target", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow(main_window, frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()