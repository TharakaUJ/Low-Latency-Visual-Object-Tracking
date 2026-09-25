import os
import cv2
import torch
import numpy as np
from ultralytics import YOLO

# 1. Configuration
MODEL_NAME = "yolov8n.pt"  # or 'yolo11n.pt'
IMAGE_PATH = "/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/software_testing/data/horse.jpg"
OUTPUT_DIR = "yolo_filters_dissected"

# Choose which layer indices you want to extract (e.g., Layer 0, Layer 1, Layer 2)
# Keep it small initially; a single layer can have 32 to 64 filters!
LAYERS_TO_EXTRACT = [0, 1] 

# 2. Setup model and image
model = YOLO(MODEL_NAME)
pure_pytorch_model = model.model  # Get the raw PyTorch module

# Preprocess image into a tensor compatible with the model
img = cv2.imread(IMAGE_PATH)
img_resized = cv2.resize(img, (640, 640))
# Convert to float32, reorder channels (BGR -> RGB), scale to 0-1, add batch dim
img_tensor = img_resized.transpose(2, 0, 1)[np.newaxis, ...]
img_tensor = torch.from_numpy(img_tensor).float() / 255.0

# Move tensor to the same device as the model (CPU or GPU)
device = next(pure_pytorch_model.parameters()).device
img_tensor = img_tensor.to(device)

# 3. Dissect the model layer by layer
x = img_tensor
with torch.no_grad():
    for i, layer_block in enumerate(pure_pytorch_model.model):
        # Pass the data through the current layer block
        x = layer_block(x)
        
        if i in LAYERS_TO_EXTRACT:
            print(f"Processing Layer {i}... Output Shape: {x.shape}")
            layer_dir = os.path.join(OUTPUT_DIR, f"layer_{i}")
            os.makedirs(layer_dir, exist_ok=True)
            
            # Squeeze out the batch dimension -> shape becomes (channels, height, width)
            feature_maps = x.squeeze(0).cpu().numpy()
            num_filters = feature_maps.shape[0]
            
            # Iterate through EVERY individual filter channel
            for filter_idx in range(num_filters):
                f_map = feature_maps[filter_idx]
                
                # Normalize the values between 0 and 255 for clean viewing
                f_map -= f_map.min()
                if f_map.max() > 0:
                    f_map /= f_map.max()
                f_map = (f_map * 255).astype(np.uint8)
                
                # Upscale the tiny internal resolution back to 640x640 so it's sharp
                f_map_resized = cv2.resize(f_map, (640, 640), interpolation=cv2.INTER_NEAREST)
                
                # Apply a color map (like JET or VIRIDIS) to make activations highly visible
                color_mapped = cv2.applyColorMap(f_map_resized, cv2.COLORMAP_VIRIDIS)
                
                # Save the standalone filter image
                filename = os.path.join(layer_dir, f"filter_{filter_idx}.png")
                cv2.imwrite(filename, color_mapped)
                
            print(f" Successfully saved {num_filters} individual filter images for Layer {i}!")
