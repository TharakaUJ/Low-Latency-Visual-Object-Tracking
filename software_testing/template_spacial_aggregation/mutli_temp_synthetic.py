import numpy as np
import cv2

def sad_matching(image, template, stride=1):
    th, tw = template.shape
    h, w = image.shape
    if h < th or w < tw: return 0, 0, float('inf'), None
    
    # Vectorized sliding window SAD for fast Python simulation
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
    max_dx = max(off[0] for off in offsets)
    max_dy = max(off[1] for off in offsets)
    
    out_H, out_W = H_map - max_dy, W_map - max_dx
    combined_sad = np.zeros((out_H, out_W), dtype=np.int32)
    
    for s_map, (dx, dy) in zip(sad_maps, offsets):
        combined_sad += s_map[dy:dy+out_H, dx:dx+out_W]
        
    combined_sad_strided = combined_sad[::stride, ::stride]
    min_idx = np.unravel_index(np.argmin(combined_sad_strided), combined_sad_strided.shape)
    return min_idx[1] * stride, min_idx[0] * stride, combined_sad_strided[min_idx]

def downsample_2x(img):
    img16 = img.astype(np.uint16)
    out = (img16[0::2, 0::2] + img16[0::2, 1::2] + img16[1::2, 0::2] + img16[1::2, 1::2]) >> 2
    return out.astype(np.uint8)

def downsample_4x(img):
    return downsample_2x(downsample_2x(img))

def run_synthetic_benchmark():
    np.random.seed(42)
    # Target: 32x32 object
    target = np.ones((32, 32), dtype=np.uint8) * 150
    cv2.circle(target, (16, 16), 10, 255, -1)
    
    # Extract templates
    t_base = target[8:24, 8:24]
    t_multi_2 = [target[8:24, 0:16], target[8:24, 16:32]]
    t_multi_4 = [target[0:16, 0:16], target[0:16, 16:32], target[16:32, 0:16], target[16:32, 16:32]]
    
    t_down_2 = downsample_2x(target) # 16x16
    t_down_4 = downsample_4x(np.pad(target, 16, mode='edge'))[4:20, 4:20] # 16x16 approx
    
    results = { "Baseline 16x16": [], "Multi 2x1": [], "Multi 2x2": [], "Down 2x": [], "Down 4x": [] }
    
    for i in range(100):
        bg = np.random.randint(0, 50, (240, 320), dtype=np.uint8)
        # Clutter that looks like the target center
        cv2.circle(bg, (116, 116), 10, 255, -1) 
        
        # Ground truth motion
        x, y = 40 + i * 2, 50 + int(20 * np.sin(i / 5.0))
        
        frame = bg.copy()
        frame[y:y+32, x:x+32] = target
        
        # Add harsh occlusion (frames 40-50)
        if 40 < i < 50: frame[y+16:y+32, x:x+32] = 0
            
        # 1. Baseline
        bx, by, _, _ = sad_matching(frame, t_base)
        results["Baseline 16x16"].append((bx-8, by-8)) # Adjust center
        
        # 2. Multi 2
        mx2, my2, _ = track_multi(frame, t_multi_2, [(0,0), (16,0)])
        results["Multi 2x1"].append((mx2, my2-8))
        
        # 3. Multi 4
        mx4, my4, _ = track_multi(frame, t_multi_4, [(0,0), (16,0), (0,16), (16,16)])
        results["Multi 2x2"].append((mx4, my4))
        
        # 4. Down 2x
        d2x, d2y, _, _ = sad_matching(downsample_2x(frame), t_down_2)
        results["Down 2x"].append((d2x*2, d2y*2))
        
        # 5. Down 4x
        d4x, d4y, _, _ = sad_matching(downsample_4x(frame), t_down_4)
        results["Down 4x"].append((d4x*4, d4y*4))

        results["GT"] = results.get("GT", []) + [(x, y)]

    # Analysis
    print(f"{'Method':<15} | {'Mean Err':<10} | {'Max Err':<10} | {'Max Jitter':<10}")
    print("-" * 55)
    gt = np.array(results["GT"])
    for name, preds in results.items():
        if name == "GT": continue
        preds = np.array(preds)
        errors = np.linalg.norm(preds - gt, axis=1)
        jitter = np.linalg.norm(preds[1:] - preds[:-1], axis=1)
        print(f"{name:<15} | {np.mean(errors):<10.2f} | {np.max(errors):<10.2f} | {np.max(jitter):<10.2f}")

if __name__ == "__main__":
    run_synthetic_benchmark()