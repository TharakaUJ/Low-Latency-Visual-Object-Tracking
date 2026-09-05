import cv2
import time
import torch

# Import LightFC modules (adjust path imports according to your local repo setup)
from lib.config.lightfc.config import cfg, update_config_from_file
from lib.test.tracker.lightfc import LightFC


def benchmark_lightfc_video(
    video_path,
    config_path,
    checkpoint_path,
    initial_bbox=None,
    device="cuda",
):
    """
    Benchmarks LightFC tracker on a video stream with real-time visualization.
    """
    print(f"Loading LightFC model on device '{device}'...")

    # Load tracker configuration and weight checkpoint
    update_config_from_file(config_path)
    tracker = LightFC(cfg, checkpoint_path)

    # Initialize video capture
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{video_path}'.")
        return

    # Read the first frame to initialize template tracking
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame from video.")
        cap.release()
        return

    # Prompt user to draw ROI bounding box if none was supplied
    if initial_bbox is None:
        print(
            "Select target object bounding box in GUI window and press SPACE/ENTER..."
        )
        # cv2.selectROI returns (x, y, width, height)
        roi = cv2.selectROI(
            "Select Target ROI (LightFC)", frame, fromCenter=False, showCrosshair=True
        )
        cv2.destroyWindow("Select Target ROI (LightFC)")

        if roi == (0, 0, 0, 0):
            print("No target selected. Exiting benchmark.")
            cap.release()
            return
        initial_bbox = list(roi)

    print(f"Initializing target template at bbox [x, y, w, h]: {initial_bbox}")

    # Set initial target template on Frame 0
    tracker.initialize(frame, {"init_bbox": initial_bbox})

    # Tracking variables for benchmark statistics
    frame_count = 0
    total_inference_time_ms = 0
    start_total_time = time.time()

    print(
        "Starting video tracking benchmark... (Press 'q' in the video window to stop)"
    )

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Start inference timer
        start_infer = time.perf_counter()

        # Run LightFC search frame tracking step
        out = tracker.track(frame)

        # Force CUDA sync for precise latency timing if running on GPU
        if device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.synchronize()

        # End inference timer
        end_infer = time.perf_counter()

        # Calculate timing for the current frame
        inference_time_ms = (end_infer - start_infer) * 1000
        total_inference_time_ms += inference_time_ms
        frame_count += 1

        # Calculate instant FPS
        fps = 1000.0 / inference_time_ms if inference_time_ms > 0 else 0

        # Extract tracked bounding box coordinates [x, y, w, h]
        bbox = out["target_bbox"]
        x, y, w, h = map(int, bbox)

        # Draw target tracking bounding box
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Overlay performance statistics
        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 150),
            2,
        )
        cv2.putText(
            frame,
            f"Inference: {inference_time_ms:.1f} ms",
            (20, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 150),
            2,
        )

        # Display the video feed
        cv2.imshow("LightFC Video Tracking Benchmark", frame)

        # Exit condition
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Benchmark interrupted by user.")
            break

    # Cleanup
    cap.release()
    cv2.destroyAllWindows()

    # Calculate and display final aggregate statistics
    total_time = time.time() - start_total_time
    avg_inference_ms = (
        total_inference_time_ms / frame_count if frame_count > 0 else 0
    )
    avg_fps = frame_count / total_time if total_time > 0 else 0

    print("\n--- Final Benchmark Results ---")
    print(f"Total Frames Processed: {frame_count}")
    print(f"Average Inference Time: {avg_inference_ms:.2f} ms/frame")
    print(f"Average Total FPS:      {avg_fps:.2f} frames/sec")


if __name__ == "__main__":
    # Video source (Path to video file or 0 for local webcam)
    video_source = "test_video.mp4"

    # Path to your LightFC experiment YAML config and weights
    config_file = "experiments/lightfc/mobilnetv2_p_pwcorr_se_scf_sc_iab_sc_adj_concat_repn33_se_conv33_center_wiou.yaml"
    model_checkpoint = "checkpoints/lightfc_mobilenetv2.pth"

    # Preset bounding box [x, y, width, height]
    # Set to None to interactively draw a box on frame 0 using mouse
    preset_target_bbox = [250, 150, 100, 120]

    benchmark_lightfc_video(
        video_path=video_source,
        config_path=config_file,
        checkpoint_path=model_checkpoint,
        initial_bbox=preset_target_bbox,
        device="cuda",  # Use 'cuda' or 'cpu'
    )