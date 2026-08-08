import cv2
import time
from ultralytics import YOLO

def benchmark_yoloe_tracking(video_path, prompt_classes, tracker_type="bytetrack.yaml", model_weights="yoloe-26n-seg.pt"):
    """
    Benchmarks YOLOE tracking pipeline using open-vocabulary text prompts.
    """
    print(f"Loading YOLOE model from '{model_weights}'...")
    model = YOLO(model_weights)
    
    print(f"Setting open-vocabulary prompts: {prompt_classes}")
    text_embeddings = model.get_text_pe(prompt_classes)
    model.set_classes(prompt_classes, text_embeddings)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{video_path}'.")
        return

    frame_count = 0
    total_time_ms = 0
    start_total_time = time.time()
    
    print(f"Starting tracking benchmark using {tracker_type}... (Press 'q' to stop)")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        start_infer = time.perf_counter()
        
        # track() replaces predict()
        # persist=True ensures IDs are passed from frame to frame
        results = model.track(frame, persist=True, tracker=tracker_type, verbose=False) 
        
        end_infer = time.perf_counter()
        
        pipeline_time_ms = (end_infer - start_infer) * 1000
        total_time_ms += pipeline_time_ms
        frame_count += 1
        
        fps = 1000.0 / pipeline_time_ms if pipeline_time_ms > 0 else 0
        
        # plot() automatically renders tracking IDs when persist=True is active
        annotated_frame = results[0].plot()
        
        cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
        cv2.putText(annotated_frame, f"Pipeline: {pipeline_time_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
                    
        cv2.imshow("YOLOE Tracking Benchmark", annotated_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    
    total_run_time = time.time() - start_total_time
    avg_pipeline_ms = total_time_ms / frame_count if frame_count > 0 else 0
    avg_fps = frame_count / total_run_time if total_run_time > 0 else 0
    
    print("\n--- Final Tracking Benchmark Results ---")
    print(f"Tracker Algorithm:      {tracker_type}")
    print(f"Total Frames Processed: {frame_count}")
    print(f"Avg Pipeline Time:      {avg_pipeline_ms:.2f} ms/frame")
    print(f"Average Total FPS:      {avg_fps:.2f} frames/sec")

if __name__ == "__main__":
    custom_prompts = ["car"]
    
    benchmark_yoloe_tracking(
        video_path="test_video.mp4", 
        prompt_classes=custom_prompts,
        tracker_type="bytetrack.yaml", 
        # Using the Nano model here since you are benchmarking on a laptop CPU
        model_weights="yoloe-26n-seg.pt"  
    )