import cv2
import time
import torch
import sys

# NanoDet imports (Ensure you are running this from the nanodet repository root)
try:
    from nanodet.util import cfg, load_config, Logger
    from demo.demo import Predictor
except ImportError:
    print("Error: NanoDet modules not found.")
    print("Please run this script from the root directory of the official NanoDet repository:")
    print("https://github.com/RangiLyu/nanodet")
    sys.exit(1)

def benchmark_nanodet_video(video_path, config_path, model_weights):
    """
    Benchmarks NanoDet on a video stream.
    NanoDet is a high-speed, lightweight anchor-free object detector.
    """
    print(f"Loading NanoDet config from '{config_path}'...")
    # Load the YAML configuration file
    load_config(cfg, config_path)
    
    # Initialize logger (required by NanoDet's Predictor)
    logger = Logger(-1, use_tensorboard=False)
    
    # Setup device (GPU if available, else fallback to CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    print(f"Loading NanoDet model weights from '{model_weights}'...")
    # Initialize Predictor (handles model building, weight loading, and preprocessing)
    predictor = Predictor(cfg, model_weights, logger, device=device)
    
    # Initialize video capture
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{video_path}'.")
        return

    # Tracking variables for benchmark statistics
    frame_count = 0
    total_inference_time_ms = 0
    start_total_time = time.time()
    
    print("Starting video inference benchmark... (Press 'q' in the video window to stop)")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Start inference timer
        start_infer = time.perf_counter()
        
        # Run prediction on the frame
        # 'meta' contains raw image info, 'res' contains bounding boxes and scores
        meta, res = predictor.inference(frame)
        
        # End inference timer
        end_infer = time.perf_counter()
        
        # Calculate timing for the current frame
        inference_time_ms = (end_infer - start_infer) * 1000
        total_inference_time_ms += inference_time_ms
        frame_count += 1
        
        # Calculate instant FPS
        fps = 1000.0 / inference_time_ms if inference_time_ms > 0 else 0
        
        # Render bounding boxes on the frame (res[0] gets the first batch item)
        annotated_frame = predictor.visualize(res[0], meta, cfg.class_names, score_thres=0.35)
        
        # Overlay performance statistics
        cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
        cv2.putText(annotated_frame, f"Inference: {inference_time_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
                    
        # Display the video feed
        cv2.imshow("NanoDet Benchmark", annotated_frame)
        
        # Exit condition
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Benchmark interrupted by user.")
            break

    # Cleanup
    cap.release()
    cv2.destroyAllWindows()
    
    # Calculate and display final aggregate statistics
    total_time = time.time() - start_total_time
    avg_inference_ms = total_inference_time_ms / frame_count if frame_count > 0 else 0
    avg_fps = frame_count / total_time if total_time > 0 else 0
    
    print("\n--- Final Benchmark Results ---")
    print(f"Total Frames Processed: {frame_count}")
    print(f"Average Inference Time: {avg_inference_ms:.2f} ms/frame")
    print(f"Average Total FPS:      {avg_fps:.2f} frames/sec")

if __name__ == "__main__":
    # Path to your video file (or use 0 for local webcam)
    video_source = "test_video.mp4" 
    
    # Use the lightest model available (nanodet-plus-m_320)
    # Ensure you have downloaded the weights into your working directory
    benchmark_nanodet_video(
        video_path=video_source, 
        config_path="config/nanodet-plus-m_320.yml",
        model_weights="nanodet-plus-m_320.pth"  
    )