import cv2
import time
from ultralytics import YOLO

def benchmark_yoloe_video_intel(video_path, prompt_classes, model_weights="yoloe-26n-seg.pt"):
    """
    Benchmarks YOLOE on a video stream using an Intel GPU via OpenVINO, 
    with ByteTrack object tracking.
    """
    print(f"Loading base YOLOE model from '{model_weights}'...")
    model = YOLO(model_weights)
    
    print(f"Setting open-vocabulary prompts: {prompt_classes}")
    # Compute and lock the CLIP-style embeddings BEFORE export
    text_embeddings = model.get_text_pe(prompt_classes)
    model.set_classes(prompt_classes, text_embeddings)
    
    print("Exporting model to OpenVINO for Intel GPU optimization...")
    # Export the model. This saves it to a local directory (e.g., 'yoloe-26n-seg_openvino_model')
    export_dir = model.export(format="openvino")
    
    print(f"Loading optimized OpenVINO model from '{export_dir}'...")
    # Load the OpenVINO exported model rather than the base PyTorch model
    ov_model = YOLO(export_dir)

    # Initialize video capture
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{video_path}'.")
        return

    frame_count = 0
    total_inference_time_ms = 0
    start_total_time = time.time()
    
    print("Starting video inference & ByteTrack benchmark on Intel GPU... (Press 'q' to stop)")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        start_infer = time.perf_counter()
        
        # CHANGED: Use .track() instead of .predict()
        # persist=True is required for video tracking to keep IDs across frames
        # tracker="bytetrack.yaml" tells Ultralytics to use the ByteTrack algorithm
        results = ov_model.track(
            frame, 
            persist=True, 
            tracker="bytetrack.yaml", 
            device="intel:gpu", 
            verbose=False
        ) 
        
        end_infer = time.perf_counter()
        
        inference_time_ms = (end_infer - start_infer) * 1000
        total_inference_time_ms += inference_time_ms
        frame_count += 1
        
        fps = 1000.0 / inference_time_ms if inference_time_ms > 0 else 0
        
        # .plot() will now automatically render the unique tracking IDs alongside bounding boxes
        annotated_frame = results[0].plot()
        
        cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
        cv2.putText(annotated_frame, f"Inference: {inference_time_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 150), 2)
                    
        cv2.imshow("YOLOE OpenVINO Intel GPU + ByteTrack", annotated_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Benchmark interrupted by user.")
            break

    cap.release()
    cv2.destroyAllWindows()
    
    total_time = time.time() - start_total_time
    avg_inference_ms = total_inference_time_ms / frame_count if frame_count > 0 else 0
    avg_fps = frame_count / total_time if total_time > 0 else 0
    
    print("\n--- Final Benchmark Results ---")
    print(f"Total Frames Processed: {frame_count}")
    print(f"Average Inference Time: {avg_inference_ms:.2f} ms/frame")
    print(f"Average Total FPS:      {avg_fps:.2f} frames/sec")

if __name__ == "__main__":
    custom_prompts = ["car"]
    video_source = "test_video.mp4" 
    
    benchmark_yoloe_video_intel(
        video_path=video_source, 
        prompt_classes=custom_prompts,
        model_weights="yoloe-26n-seg.pt"  
    )