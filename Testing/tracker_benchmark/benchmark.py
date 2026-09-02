# tracker_benchmark/benchmark.py
import argparse
import cv2
import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm
from trackers.methods import StaticTracker, DynamicTracker, DualTracker, SobelTracker, ConvTracker
from evaluation import calculate_iou, calculate_center_error
from config import IOU_THRESHOLD

TRACKERS = {
    'static': StaticTracker,
    'dynamic': DynamicTracker,
    'dual': DualTracker,
    'sobel': SobelTracker,
    'conv1': lambda: ConvTracker(layers=1),
    'conv2': lambda: ConvTracker(layers=2)
}

def load_groundtruth(csv_path):
    # Expected format: frame,x,y,width,height
    df = pd.read_csv(csv_path)
    return {row['frame']: [row['x'], row['y'], row['width'], row['height']] for _, row in df.iterrows()}

def run_benchmark(video_path, gt_dict, method_name, visualize):
    tracker = TRACKERS[method_name]()
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError("Cannot open video")

    frame_idx = 0
    results = []
    
    # Init
    ret, frame = cap.read()
    init_bbox = gt_dict.get(0)
    if init_bbox is None:
        init_bbox = cv2.selectROI("Select Target", frame, False)
        cv2.destroyWindow("Select Target")
        
    tracker.initialize(frame, init_bbox)
    full_frame_pixels = frame.shape[0] * frame.shape[1]
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        
        pred_bbox, conf, elapsed = tracker.update(frame)
        
        gt_bbox = gt_dict.get(frame_idx, None)
        iou, center_err = 0.0, 0.0
        
        if gt_bbox:
            iou = calculate_iou(pred_bbox, gt_bbox)
            center_err = calculate_center_error(pred_bbox, gt_bbox)
            
        results.append({
            'frame': frame_idx,
            'iou': iou,
            'center_error': center_err,
            'confidence': conf,
            'elapsed_s': elapsed,
            'macs': tracker.macs,
            'pixels_processed': tracker.pixels_processed,
            'full_frame_pixels': full_frame_pixels
        })
        
        if visualize:
            # Draw tracking
            x, y, w, h = map(int, pred_bbox)
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # Draw Search Region
            cx, cy = int(x + w/2), int(y + h/2)
            cv2.rectangle(frame, (cx-80, cy-80), (cx+80, cy+80), (255, 0, 0), 1)
            
            cv2.putText(frame, f"{method_name} | FPS: {1/(elapsed+1e-6):.1f} | Conf: {conf:.2f}", 
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            cv2.imshow("Tracking", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()
    return pd.DataFrame(results)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', required=True)
    parser.add_argument('--gt', default=None)
    parser.add_argument('--method', choices=list(TRACKERS.keys())+['all'], default='all')
    parser.add_argument('--visualize', action='store_true')
    args = parser.parse_args()

    gt_dict = load_groundtruth(args.gt) if args.gt else {}
    methods_to_run = list(TRACKERS.keys()) if args.method == 'all' else [args.method]
    
    summary = []
    all_results = {}
    
    for method in methods_to_run:
        print(f"Running {method}...")
        df = run_benchmark(args.video, gt_dict, method, args.visualize)
        all_results[method] = df
        
        # Aggregate metrics
        mean_iou = df['iou'].mean()
        success_rate = (df['iou'] >= IOU_THRESHOLD).mean()
        mean_fps = 1.0 / df['elapsed_s'].mean()
        failure_count = (df['confidence'] < 0.6).sum()
        
        # Hardware savings
        pix_proc = df['pixels_processed'].iloc[0]
        ff_pix = df['full_frame_pixels'].iloc[0]
        savings = (1 - (pix_proc / ff_pix)) * 100
        
        summary.append({
            'Method': method,
            'Mean_IoU': round(mean_iou, 3),
            'Success_Rate': round(success_rate, 3),
            'FPS': round(mean_fps, 1),
            'Failures': failure_count,
            'Est_MACs': int(df['macs'].mean()),
            'Pixel_Reduction_%': round(savings, 1)
        })

    summary_df = pd.DataFrame(summary)
    print("\n--- Benchmark Results ---")
    print(summary_df.to_string(index=False))
    summary_df.to_csv("results/benchmark_summary.csv", index=False)
    
    # Generate Plots
    if len(methods_to_run) > 1:
        plt.figure(figsize=(10, 6))
        for m in methods_to_run:
            plt.scatter(summary_df[summary_df['Method']==m]['Est_MACs'], 
                        summary_df[summary_df['Method']==m]['Mean_IoU'], 
                        label=m, s=100)
        plt.plot(summary_df['Est_MACs'], summary_df['Mean_IoU'], 'k--', alpha=0.3)
        plt.xlabel("Estimated Computational Complexity (MACs / frame)")
        plt.ylabel("Mean IoU")
        plt.title("Tracking Accuracy vs Computational Cost")
        plt.legend()
        plt.grid(True)
        plt.savefig("results/accuracy_vs_cost.png")
        print("\nSaved plot to results/accuracy_vs_cost.png")

if __name__ == '__main__':
    main()