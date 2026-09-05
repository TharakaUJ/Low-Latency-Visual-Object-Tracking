# tracker_benchmark/trackers/methods.py
import cv2
import numpy as np
from .base import BaseTracker
from config import CONF_THRESHOLD, ALPHA, TEMPLATE_SIZE

class StaticTracker(BaseTracker):
    """Method 1: Single static template"""
    def track_step(self, search_region):
        res = cv2.matchTemplate(search_region, self.t_orig, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        self.macs += self._estimate_correlation_macs()
        return max_loc, max_val

class DynamicTracker(BaseTracker):
    """Method 2: Latest template only"""
    def track_step(self, search_region):
        res = cv2.matchTemplate(search_region, self.t_latest, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        self.macs += self._estimate_correlation_macs()
        
        if max_val > CONF_THRESHOLD:
            # Extract new template at matched location
            cx = max_loc[0] + TEMPLATE_SIZE // 2
            cy = max_loc[1] + TEMPLATE_SIZE // 2
            self.t_latest = self._extract_region(search_region, (cx,cy), TEMPLATE_SIZE)
            
        return max_loc, max_val

class DualTracker(BaseTracker):
    """Method 3: Alpha blended Original + Latest template"""
    def track_step(self, search_region):
        res_orig = cv2.matchTemplate(search_region, self.t_orig, cv2.TM_CCOEFF_NORMED)
        res_latest = cv2.matchTemplate(search_region, self.t_latest, cv2.TM_CCOEFF_NORMED)
        
        res_combined = ALPHA * res_orig + (1 - ALPHA) * res_latest
        _, max_val, _, max_loc = cv2.minMaxLoc(res_combined)
        
        self.macs += 2 * self._estimate_correlation_macs()
        
        if max_val > CONF_THRESHOLD:
            cx = max_loc[0] + TEMPLATE_SIZE // 2
            cy = max_loc[1] + TEMPLATE_SIZE // 2
            self.t_latest = self._extract_region(search_region, (cx,cy), TEMPLATE_SIZE)
            
        return max_loc, max_val

class SobelTracker(BaseTracker):
    """Method 4: Gradient Representation (Sobel Magnitude)"""
    def initialize(self, frame, bbox):
        super().initialize(frame, bbox)
        self.t_orig = self._to_sobel(self.t_orig)
        
    def _to_sobel(self, img):
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        return cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    def track_step(self, search_region):
        sr_sobel = self._to_sobel(search_region)
        res = cv2.matchTemplate(sr_sobel, self.t_orig, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        # Sobel MACs: roughly 2 * 9 MACs per pixel in search region
        self.macs += 18 * (search_region.shape[0] * search_region.shape[1])
        self.macs += self._estimate_correlation_macs()
        
        return max_loc, max_val

class ConvTracker(BaseTracker):
    """Method 5 & 6: Minimal Convolutional Feature Extractor"""
    def __init__(self, layers=1):
        super().__init__()
        self.layers = layers
        # Simulated manual weights: simple edge/ridge detectors for robust features
        self.k1 = np.array([[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]], dtype=np.float32)
        self.k2 = np.array([[1, 2, 1], [0, 0, 0], [-1, -2, -1]], dtype=np.float32)
        
    def initialize(self, frame, bbox):
        super().initialize(frame, bbox)
        self.t_orig = self._forward_pass(self.t_orig)
        
    def _forward_pass(self, img):
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
            
        # Layer 1
        x = cv2.filter2D(img, -1, self.k1)
        x = np.maximum(0, x) # ReLU
        self.macs += 9 * img.size
        
        if self.layers == 2:
            # Layer 2
            x = cv2.filter2D(x, -1, self.k2)
            x = np.maximum(0, x) # ReLU
            self.macs += 9 * img.size
            
        return cv2.normalize(x, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    def track_step(self, search_region):
        sr_features = self._forward_pass(search_region)
        res = cv2.matchTemplate(sr_features, self.t_orig, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        self.macs += self._estimate_correlation_macs()
        return max_loc, max_val