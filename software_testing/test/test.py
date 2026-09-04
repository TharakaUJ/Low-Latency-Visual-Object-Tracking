import cv2
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import time
import argparse
from ultralytics import YOLO

# ==========================================
# CONFIGURATION
# ==========================================
class Config:
    TILE_SIZE = 32
    HEAVY_MODEL_INTERVAL = 60      # Run heavy model every N frames
    CONFIDENCE_THRESHOLD = 0.6     # Trigger heavy model if lightweight score drops below this
    SEARCH_GRID = 5                # 5x5 grid of candidate windows
    SEARCH_STRIDE = 4              # Pixels between candidate windows
    TARGET_CLASS = 0               # 0 = Person in COCO dataset
    LEARNING_RATE = 0.05           # For dynamic weight adaptation
    ADAPTATION_STEPS = 10          # SGD steps to fit dynamic layer
    USE_CONFIDENCE_TRIGGER = True
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

# ==========================================
# LIGHTWEIGHT MODEL ARCHITECTURE
# ==========================================
class LightweightFeatureExtractor(nn.Module):
    def __init__(self):
        super().__init__()
        # 32x32x1 -> 16x16x8 -> 8x8x16 -> 4x4x16 -> Flat(256)
        # Intentionally tiny, using stride 2 instead of MaxPool for FPGA simplicity
        self.fixed_layers = nn.Sequential(
            nn.Conv2d(1, 8, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(8, 16, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 16, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten()
        )
        
    def forward(self, x):
        return self.fixed_layers(x)

# ==========================================
# TRACKING SYSTEM
# ==========================================
class DynamicTracker:
    def __init__(self, config):
        self.cfg = config
        self.feature_extractor = LightweightFeatureExtractor().to(self.cfg.DEVICE)
        self.feature_extractor.eval() # Fixed weights
        
        # The dynamic layer: 256 inputs -> 1 output (Score)
        self.dynamic_layer = nn.Linear(256, 1).to(self.cfg.DEVICE)
        self.criterion = nn.BCEWithLogitsLoss()
        
        self.current_bbox = None # [x1, y1, x2, y2]
        
    def _get_tile(self, frame, bbox):
        x1, y1, x2, y2 = map(int, bbox)
        h, w = frame.shape[:2]
        # Clamp to frame
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return np.zeros((self.cfg.TILE_SIZE, self.cfg.TILE_SIZE), dtype=np.float32)
            
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        crop_resized = cv2.resize(crop_gray, (self.cfg.TILE_SIZE, self.cfg.TILE_SIZE))
        crop_normalized = crop_resized.astype(np.float32) / 255.0
        return crop_normalized

    def adapt(self, frame, target_bbox):
        """Option B: Target-dependent parameter fitting"""
        self.current_bbox = target_bbox
        
        # 1. Generate Positive Sample
        pos_tile = self._get_tile(frame, target_bbox)
        
        # 2. Generate Negative Samples (Background)
        neg_tiles = []
        w_box = target_bbox[2] - target_bbox[0]
        h_box = target_bbox[3] - target_bbox[1]
        
        shifts = [(-1, 0), (1, 0), (0, -1), (0, 1)] # Shift bounding box up/down/left/right
        for dx, dy in shifts:
            neg_box = [
                target_bbox[0] + dx * w_box, target_bbox[1] + dy * h_box,
                target_bbox[2] + dx * w_box, target_bbox[3] + dy * h_box
            ]
            neg_tiles.append(self._get_tile(frame, neg_box))
            
        # 3. Prepare Batch
        tiles = np.stack([pos_tile] + neg_tiles)
        tiles_tensor = torch.tensor(tiles).unsqueeze(1).to(self.cfg.DEVICE) # [B, 1, 32, 32]
        labels = torch.tensor([[1.0]] + [[0.0]] * len(neg_tiles)).to(self.cfg.DEVICE)
        
        # 4. Fit Dynamic Layer
        optimizer = optim.SGD(self.dynamic_layer.parameters(), lr=self.cfg.LEARNING_RATE)
        
        with torch.no_grad():
            features = self.feature_extractor(tiles_tensor) # Extract fixed features once
            
        for _ in range(self.cfg.ADAPTATION_STEPS):
            optimizer.zero_grad()
            scores = self.dynamic_layer(features)
            loss = self.criterion(scores, labels)
            loss.backward()
            optimizer.step()

    def track(self, frame):
        if self.current_bbox is None:
            return None, 0.0
            
        x1, y1, x2, y2 = self.current_bbox
        w_box, h_box = x2 - x1, y2 - y1
        cx, cy = x1 + w_box/2, y1 + h_box/2
        
        # Generate search grid
        candidates = []
        bboxes = []
        offset = (self.cfg.SEARCH_GRID // 2) * self.cfg.SEARCH_STRIDE
        
        for dy in range(-offset, offset + 1, self.cfg.SEARCH_STRIDE):
            for dx in range(-offset, offset + 1, self.cfg.SEARCH_STRIDE):
                cand_cx, cand_cy = cx + dx, cy + dy
                cand_box = [cand_cx - w_box/2, cand_cy - h_box/2, cand_cx + w_box/2, cand_cy + h_box/2]
                candidates.append(self._get_tile(frame, cand_box))
                bboxes.append(cand_box)
                
        # Batch inference
        tiles_tensor = torch.tensor(np.stack(candidates)).unsqueeze(1).to(self.cfg.DEVICE)
        
        with torch.no_grad():
            features = self.feature_extractor(tiles_tensor)
            logits = self.dynamic_layer(features)
            probs = torch.sigmoid(logits).cpu().numpy().flatten()
            
        best_idx = np.argmax(probs)
        best_score = probs[best_idx]
        self.current_bbox = bboxes[best_idx]
        
        return self.current_bbox, best_score

# ==========================================
# MAIN EXPERIMENT PIPELINE
# ==========================================
def run_experiment(source):
    cfg = Config()
    
    # Initialize Models
    print("Loading Heavy Model (YOLOv8)...")
    heavy_model = YOLO('yolov8n.pt') 
    tracker = DynamicTracker(cfg)
    
    cap = cv2.VideoCapture(source)
    
    frame_count = 0
    frames_since_correction = 0
    dynamic_weights_version = 0
    target_lost = True
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        start_time = time.time()
        heavy_active = False
        confidence = 0.0
        
        # Trigger Heavy Model Logic
        time_to_update = (frames_since_correction >= cfg.HEAVY_MODEL_INTERVAL)
        
        if target_lost or time_to_update:
            heavy_active = True
            results = heavy_model(frame, classes=[cfg.TARGET_CLASS], verbose=False)[0]
            
            if len(results.boxes) > 0:
                # Take largest box
                boxes = results.boxes.xyxy.cpu().numpy()
                areas = (boxes[:,2]-boxes[:,0]) * (boxes[:,3]-boxes[:,1])
                best_box = boxes[np.argmax(areas)]
                
                # ADAPT LIGHTWEIGHT MODEL
                tracker.adapt(frame, best_box)
                dynamic_weights_version += 1
                frames_since_correction = 0
                target_lost = False
                tracked_bbox = best_box
                confidence = 1.0 # Heavy model confidence
            else:
                tracked_bbox = None
                target_lost = True
        else:
            # RUN LIGHTWEIGHT MODEL
            tracked_bbox, confidence = tracker.track(frame)
            frames_since_correction += 1
            
            # Confidence Check
            if cfg.USE_CONFIDENCE_TRIGGER and confidence < cfg.CONFIDENCE_THRESHOLD:
                target_lost = True # Will trigger heavy model next frame

        fps = 1.0 / (time.time() - start_time)
        
        # ==========================================
        # VISUALIZATION
        # ==========================================
        vis_frame = frame.copy()
        if tracked_bbox is not None:
            color = (0, 0, 255) if heavy_active else (0, 255, 0)
            x1, y1, x2, y2 = map(int, tracked_bbox)
            cv2.rectangle(vis_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(vis_frame, f"Target", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
        # HUD
        hud = [
            f"FPS: {fps:.1f}",
            f"Lightweight Conf: {confidence:.2f}",
            f"Heavy Model Active: {'YES' if heavy_active else 'NO'}",
            f"Dynamic Weights Ver: {dynamic_weights_version}",
            f"Frames since update: {frames_since_correction}/{cfg.HEAVY_MODEL_INTERVAL}"
        ]
        
        for i, text in enumerate(hud):
            y_pos = 30 + (i * 25)
            # Red text if heavy model is active, green otherwise
            t_color = (0, 0, 255) if heavy_active else (0, 255, 0)
            cv2.putText(vis_frame, text, (20, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 3) # Outline
            cv2.putText(vis_frame, text, (20, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, t_color, 2)

        cv2.imshow("Tracking Architecture Experiment", vis_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=str, default='0', help='Video file or 0 for webcam')
    args = parser.parse_args()
    # Handle webcam source properly
    src = 0 if args.source == '0' else args.source
    run_experiment(src)