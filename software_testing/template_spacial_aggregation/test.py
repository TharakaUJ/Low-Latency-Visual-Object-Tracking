import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import convolve
import cv2 # Only used for drawing in visualization if needed, but we'll stick to numpy/plt

class TrackerExperiment:
    def __init__(self, W=320, H=240, template_size=16, stride=4):
        self.W = W
        self.H = H
        self.T = template_size
        self.stride = stride
        
        # Grid dimensions
        self.Gw = (self.W - self.T) // self.stride + 1
        self.Gh = (self.H - self.T) // self.stride + 1
        
        # Create a distinct template (e.g., a cross with a center dot)
        self.template = np.zeros((self.T, self.T), dtype=np.float32)
        cv2.drawMarker(self.template, (self.T//2, self.T//2), 200, markerType=cv2.MARKER_CROSS, thickness=2)
        cv2.circle(self.template, (self.T//2, self.T//2), 3, 255, -1)
        
        # Distractor template (similar but slightly dimmer)
        self.distractor = self.template * 0.7
        
        # Kernels for voting
        self.kernel_cross = np.array([[0, 1, 0], 
                                      [1, 4, 1], 
                                      [0, 1, 0]])
        self.kernel_square = np.array([[1, 2, 1], 
                                       [2, 4, 2], 
                                       [1, 2, 1]])

    def generate_sequence(self, frames=50, motion_type="diagonal", noise_std=10.0):
        video = []
        ground_truth = []
        
        # Starting position
        x, y = self.W // 4, self.H // 4
        
        for t in range(frames):
            frame = np.ones((self.H, self.W), dtype=np.float32) * 50 # Background
            
            # Add distractor
            dx, dy = self.W // 2, self.H // 2
            frame[dy:dy+self.T, dx:dx+self.T] = self.distractor
            
            # Motion update (sub-pixel capable via float accumulation)
            if motion_type == "diagonal":
                x += 1.2  # Deliberately off-grid
                y += 0.8
            elif motion_type == "horizontal":
                x += 0.5
            elif motion_type == "stationary":
                pass # Stays same
                
            # Integer bounds for drawing
            ix, iy = int(round(x)), int(round(y))
            frame[iy:iy+self.T, ix:ix+self.T] = self.template
            
            # Add noise
            noise = np.random.normal(0, noise_std, frame.shape)
            frame = np.clip(frame + noise, 0, 255)
            
            video.append(frame)
            ground_truth.append((x, y))
            
        return video, ground_truth

    def compute_sad_grid(self, frame):
        grid = np.zeros((self.Gh, self.Gw), dtype=np.float32)
        # Max possible SAD for 16x16 8-bit is 16*16*255 = 65280
        max_sad = self.T * self.T * 255
        
        for gy in range(self.Gh):
            for gx in range(self.Gw):
                ix = gx * self.stride
                iy = gy * self.stride
                window = frame[iy:iy+self.T, ix:ix+self.T]
                sad = np.sum(np.abs(self.template - window))
                # Convert SAD to Score (higher is better). 
                grid[gy, gx] = max_sad - sad
                
        # Normalize grid slightly for stable thresholding, though in FPGA you'd use raw integers
        grid = np.maximum(grid - np.median(grid), 0)
        return grid

    def track(self, video):
        results = {'baseline': [], 'voting': [], 'centroid_thresh': [], 'centroid_local': [], 'top_N': []}
        
        for frame in video:
            grid = self.compute_sad_grid(frame)
            
            # A. Baseline
            gy_b, gx_b = np.unravel_index(np.argmax(grid), grid.shape)
            results['baseline'].append((gx_b * self.stride, gy_b * self.stride))
            
            # B. Spatial Voting
            voted_grid = convolve(grid, self.kernel_square, mode='constant', cval=0.0)
            gy_v, gx_v = np.unravel_index(np.argmax(voted_grid), voted_grid.shape)
            results['voting'].append((gx_v * self.stride, gy_v * self.stride))
            
            # C. Thresholded Centroid (Global)
            thresh = np.max(voted_grid) * 0.8
            y_indices, x_indices = np.nonzero(voted_grid > thresh)
            weights = voted_grid[y_indices, x_indices]
            if np.sum(weights) > 0:
                cx = np.sum(x_indices * weights) / np.sum(weights)
                cy = np.sum(y_indices * weights) / np.sum(weights)
                results['centroid_thresh'].append((cx * self.stride, cy * self.stride))
            else:
                results['centroid_thresh'].append((gx_v * self.stride, gy_v * self.stride))
                
            # D. Local Weighted Centroid (around Voting Peak)
            # 3x3 window around peak
            y_min, y_max = max(0, gy_v-1), min(self.Gh, gy_v+2)
            x_min, x_max = max(0, gx_v-1), min(self.Gw, gx_v+2)
            local_window = grid[y_min:y_max, x_min:x_max]
            
            yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
            weight_sum = np.sum(local_window)
            if weight_sum > 0:
                cx = np.sum(xx * local_window) / weight_sum
                cy = np.sum(yy * local_window) / weight_sum
                results['centroid_local'].append((cx * self.stride, cy * self.stride))
            else:
                results['centroid_local'].append((gx_v * self.stride, gy_v * self.stride))

            # E. Top-N Candidate Averaging (Hardware-friendly alternative)
            N = 5
            flat_indices = np.argsort(grid.ravel())[-N:]
            top_y, top_x = np.unravel_index(flat_indices, grid.shape)
            top_scores = grid[top_y, top_x]
            
            # Simple weighted average of the top N discrete candidates
            cx = np.sum(top_x * top_scores) / np.sum(top_scores)
            cy = np.sum(top_y * top_scores) / np.sum(top_scores)
            results['top_N'].append((cx * self.stride, cy * self.stride))
            
        return results

    def evaluate(self, ground_truth, results):
        gt = np.array(ground_truth)
        metrics = {}
        
        # Calculate motions
        gt_motion = np.linalg.norm(np.diff(gt, axis=0), axis=1)
        
        for method, preds in results.items():
            preds = np.array(preds)
            errors = np.linalg.norm(preds - gt, axis=1)
            
            pred_motion = np.linalg.norm(np.diff(preds, axis=0), axis=1)
            motion_error = np.abs(pred_motion - gt_motion)
            jumps = np.sum(motion_error > self.stride * 1.5) # Sudden jumps
            
            metrics[method] = {
                'mean_err': np.mean(errors),
                'max_err': np.max(errors),
                'jitter_err': np.mean(motion_error),
                'jumps': jumps
            }
        return metrics

# Run the Experiment
exp = TrackerExperiment(W=200, H=150, stride=4)
video, gt = exp.generate_sequence(frames=40, motion_type="diagonal", noise_std=15.0)
results = exp.track(video)
metrics = exp.evaluate(gt, results)

# Print Metrics
print(f"{'Method':<20} | {'Mean Err':<10} | {'Max Err':<10} | {'Jitter Err':<10} | {'Jumps'}")
print("-" * 65)
for m, vals in metrics.items():
    print(f"{m:<20} | {vals['mean_err']:<10.2f} | {vals['max_err']:<10.2f} | {vals['jitter_err']:<10.2f} | {vals['jumps']}")