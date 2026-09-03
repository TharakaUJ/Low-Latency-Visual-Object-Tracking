# tracker_benchmark/trackers/base.py
import cv2
import numpy as np
import time
from config import TEMPLATE_SIZE, SEARCH_SIZE

class BaseTracker:
    def __init__(self):
        self.center_pos = None
        self.target_sz = None
        self.frame_shape = None
        self.macs = 0 
        self.pixels_processed = 0

    def initialize(self, frame, bbox):
        self.frame_shape = frame.shape
        x, y, w, h = bbox
        self.center_pos = np.array([x + w/2, y + h/2])
        self.target_sz = np.array([w, h])
        
        # Initial template extraction
        self.t_orig = self._extract_region(frame, self.center_pos, TEMPLATE_SIZE)
        self.t_latest = self.t_orig.copy()
        
    def _extract_region(self, image, center, size):
        """Safely extract a region centered at 'center' with dimension 'size x size'"""
        cx, cy = int(center[0]), int(center[1])
        half_sz = size // 2
        
        # Pad image if crop goes out of bounds
        pad_x1, pad_x2 = max(0, half_sz - cx), max(0, cx + half_sz - image.shape[1])
        pad_y1, pad_y2 = max(0, half_sz - cy), max(0, cy + half_sz - image.shape[0])
        
        if any([pad_x1, pad_x2, pad_y1, pad_y2]):
            image = cv2.copyMakeBorder(image, pad_y1, pad_y2, pad_x1, pad_x2, cv2.BORDER_REPLICATE)
            cx += pad_x1
            cy += pad_y1
            
        return image[cy-half_sz : cy+half_sz, cx-half_sz : cx+half_sz].copy()

    def _estimate_correlation_macs(self):
        # Operations for standard sliding window normalized cross correlation
        # (Search_W - Temp_W + 1)^2 * (Temp_W * Temp_H)
        out_dim = SEARCH_SIZE - TEMPLATE_SIZE + 1
        return (out_dim**2) * (TEMPLATE_SIZE**2)

    def update(self, frame):
        start_time = time.perf_counter()
        
        # 1. Hardware assumption: We only load the search region from the sensor
        search_region = self._extract_region(frame, self.center_pos, SEARCH_SIZE)
        self.pixels_processed = SEARCH_SIZE * SEARCH_SIZE
        self.macs = 0
        
        # 2. Tracking specific implementation (overridden by subclasses)
        best_loc, confidence = self.track_step(search_region)
        
        # 3. Update center based on best location in search region
        # maxLoc gives top-left of matched template within the search region
        offset_x = best_loc[0] - (SEARCH_SIZE - TEMPLATE_SIZE) // 2
        offset_y = best_loc[1] - (SEARCH_SIZE - TEMPLATE_SIZE) // 2
        
        self.center_pos[0] += offset_x
        self.center_pos[1] += offset_y
        
        elapsed = time.perf_counter() - start_time
        
        # Return bbox format: [x, y, w, h]
        bbox = [
            self.center_pos[0] - self.target_sz[0]/2,
            self.center_pos[1] - self.target_sz[1]/2,
            self.target_sz[0],
            self.target_sz[1]
        ]
        return bbox, confidence, elapsed

    def track_step(self, search_region):
        raise NotImplementedError