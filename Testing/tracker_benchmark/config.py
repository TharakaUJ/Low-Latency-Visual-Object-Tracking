# tracker_benchmark/config.py

TEMPLATE_SIZE = 64      # Fixed template dimension (64x64)
SEARCH_SIZE = 320       # Local search region dimension (320x320)
CONF_THRESHOLD = 0.6    # Confidence threshold for updates/failures
ALPHA = 0.7             # Blend factor for dual template (original vs latest)

# Plotting and evaluation
IOU_THRESHOLD = 0.5