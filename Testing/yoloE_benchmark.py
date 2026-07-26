import cv2
import time
from ultralytics import YOLO

def benchmark_yoloe_video(video_path, prompt_classes, model_weights="yoloe-26n-seg.pt"):
    """
    Benchmarks YOLOE on a video stream using custom open-vocabulary text prompts.
    """
    print(f"Loading YOLOE model from '{model_weights}'...")
    # Load a YOLOE model (e.g., YOLOE-26 or YOLOE-v8 variants)
    model = YOLO(model_weights)
    
    print(f"Setting open-vocabulary prompts: {prompt_classes}")
    # Compute the CLIP-style text embeddings for the given prompts
    text_embeddings = model.get_text_pe(prompt_classes)
    
    # Lock the classes and their embeddings into the model's head
    model.set_classes(prompt_classes, text_embeddings)
    
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
        
        # Run prediction (verbose=False keeps the console clean for speed)
        results = model.predict(frame, verbose=False) 
        
        # End inference timer
        end_infer = time.perf_counter()
        
        # Calculate timing for the current frame
        inference_time_ms = (end_infer - start_infer) * 1000
        total_inference_time_ms += inference_time_ms
        frame_count += 1
        
        # Calculate instant FPS
        fps = 1000.0 / inference_time_ms if inference_time_ms > 0 else 0
        
        # Render bounding boxes and masks on the frame
        annotated_frame = results[0].plot()
        
        # Overlay performance statistics
        cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
        cv2.putText(annotated_frame, f"Inference: {inference_time_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
                    
        # Display the video feed
        cv2.imshow("YOLOE Open-Vocabulary Benchmark", annotated_frame)
        
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
    # Define your CLIP-style open-vocabulary prompts here
    # You can be highly specific (e.g., "red sports car", "person wearing a helmet")
    custom_prompts = [
        "car"
    ]
    
    # Path to your video file (or use 0 for local webcam)
    video_source = "test_video.mp4" 
    
    benchmark_yoloe_video(
        video_path=video_source, 
        prompt_classes=custom_prompts,
        model_weights="yoloe-26n-seg.pt"  
    )