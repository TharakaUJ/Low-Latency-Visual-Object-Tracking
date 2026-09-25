import cv2
import numpy as np

# --- Reuse downsample_2x, downsample_4x, sad_matching, track_multi from above ---
# (Copy the 4 functions here when running)

def downsample_2x(img):
    img16 = img.astype(np.uint16)
    out = (img16[0::2, 0::2] + img16[0::2, 1::2] + img16[1::2, 0::2] + img16[1::2, 1::2]) >> 2
    return out.astype(np.uint8)

def downsample_4x(img):
    return downsample_2x(downsample_2x(img))

def sad_matching(image, template, stride=1):
    th, tw = template.shape
    h, w = image.shape
    if h < th or w < tw: return 0, 0, float('inf'), None
    windows = np.lib.stride_tricks.sliding_window_view(image, (th, tw))
    windows_strided = windows[::stride, ::stride]
    sad = np.sum(np.abs(windows_strided.astype(np.int32) - template.astype(np.int32)), axis=(2, 3))
    min_idx = np.unravel_index(np.argmin(sad), sad.shape)
    best_y, best_x = min_idx[0] * stride, min_idx[1] * stride
    return best_x, best_y, sad[min_idx], sad

def track_multi(image, templates, offsets, stride=1):
    sad_maps = []
    for t in templates:
        _, _, _, s_map = sad_matching(image, t, stride=1)
        sad_maps.append(s_map)
    H_map, W_map = sad_maps[0].shape
    max_dx, max_dy = max(off[0] for off in offsets), max(off[1] for off in offsets)
    out_H, out_W = H_map - max_dy, W_map - max_dx
    if out_H <= 0 or out_W <= 0: return 0, 0, 0
    combined_sad = np.zeros((out_H, out_W), dtype=np.int32)
    for s_map, (dx, dy) in zip(sad_maps, offsets):
        combined_sad += s_map[dy:dy+out_H, dx:dx+out_W]
    min_idx = np.unravel_index(np.argmin(combined_sad), combined_sad.shape)
    return min_idx[1], min_idx[0], combined_sad[min_idx]

def main():
    cap = cv2.VideoCapture(0)
    mode = 1
    modes = {1: "Baseline 16x16", 2: "Multi 2x1", 3: "Multi 2x2", 4: "Down 2x", 5: "Down 4x"}
    
    tracking = False
    templates = []
    
    print("Keys: 1-5 to change mode, 'r' to select ROI, 'q' to quit.")
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        display = frame.copy()
        
        if not tracking:
            cv2.putText(display, f"Mode: {modes[mode]} (Press 'r' to init)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            if mode == 1: # Baseline
                x, y, sad, _ = sad_matching(gray, templates[0])
                cv2.rectangle(display, (x, y), (x+16, y+16), (0, 255, 0), 2)
                
            elif mode == 2: # Multi 2x1
                x, y, sad = track_multi(gray, templates, [(0,0), (16,0)])
                cv2.rectangle(display, (x, y), (x+32, y+16), (255, 150, 0), 2)
                
            elif mode == 3: # Multi 2x2
                x, y, sad = track_multi(gray, templates, [(0,0), (16,0), (0,16), (16,16)])
                cv2.rectangle(display, (x, y), (x+32, y+32), (0, 255, 255), 2)
                
            elif mode == 4: # Downsample 2x
                d_gray = downsample_2x(gray)
                dx, dy, sad, _ = sad_matching(d_gray, templates[0])
                # Scale back up for display
                cv2.rectangle(display, (dx*2, dy*2), (dx*2+32, dy*2+32), (0, 0, 255), 2)
                
            elif mode == 5: # Downsample 4x
                d_gray = downsample_4x(gray)
                dx, dy, sad, _ = sad_matching(d_gray, templates[0])
                cv2.rectangle(display, (dx*4, dy*4), (dx*4+64, dy*4+64), (255, 0, 255), 2)
                
            cv2.putText(display, f"Mode: {modes[mode]} | SAD: {sad}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Debug: show template(s)
            t_disp = np.hstack(templates) if len(templates) > 0 else templates[0]
            t_disp = cv2.cvtColor(t_disp, cv2.COLOR_GRAY2BGR)
            t_disp = cv2.resize(t_disp, (t_disp.shape[1]*3, t_disp.shape[0]*3), interpolation=cv2.INTER_NEAREST)
            display[50:50+t_disp.shape[0], 10:10+t_disp.shape[1]] = t_disp
            
        cv2.imshow("FPGA Tracker Sim", display)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): break
        elif key in [ord('1'), ord('2'), ord('3'), ord('4'), ord('5')]:
            mode = int(chr(key))
            tracking = False # Must re-init on mode change
        elif key == ord('r'):
            roi = cv2.selectROI("FPGA Tracker Sim", display, False, False)
            if roi[2] > 0 and roi[3] > 0:
                cx, cy = roi[0] + roi[2]//2, roi[1] + roi[3]//2
                
                if mode == 1:
                    templates = [gray[cy-8:cy+8, cx-8:cx+8]]
                elif mode == 2:
                    templates = [gray[cy-8:cy+8, cx-16:cx], gray[cy-8:cy+8, cx:cx+16]]
                elif mode == 3:
                    templates = [gray[cy-16:cy, cx-16:cx], gray[cy-16:cy, cx:cx+16],
                                 gray[cy:cy+16, cx-16:cx], gray[cy:cy+16, cx:cx+16]]
                elif mode == 4:
                    d_gray = downsample_2x(gray)
                    dcx, dcy = cx // 2, cy // 2
                    templates = [d_gray[dcy-8:dcy+8, dcx-8:dcx+8]]
                elif mode == 5:
                    d_gray = downsample_4x(gray)
                    dcx, dcy = cx // 4, cy // 4
                    templates = [d_gray[dcy-8:dcy+8, dcx-8:dcx+8]]
                
                tracking = True

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()