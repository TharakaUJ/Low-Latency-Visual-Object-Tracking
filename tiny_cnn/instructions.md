I'm trying to explore the idea of using streaming camera data real time anomaly detection using Tiny-CNN. The goal is to process video frames as it streams in from a camera, and identify any anomalies in the video feed using 16x16 pixel frames. 

To detect the anomalies i have a small convolutional neural network (CNN) model, which takes in 16x16 pixel windows of the video feed and outputs a prediction indicating whether the frame is normal or anomalous. Now I need to impement it in fpga unrolled so that it can process the video frames in real-time.

review and tell me if it is possible to implement that using verilog. 
you may use,
/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/tiny_cnn/tinycnn_qat_int4.onnx
/home/tharaka/Documents/Low-Latency-Visual-Object-Tracking/fpga_cnn_pipeline

for reference, but that exisitng verilog implmentation cannot support high speeds (only ~1fps which well below expected real-time performance).

you may rad the challenges it got along the way. also focus on running the model, we may get the iamge into the fpga using jtag uart or just write to memory directly.what is important is to prove that this architechture can support real-time processing of video frames at a higher frame rate than the current implementation.

if possible plan ahead for the implementation. you may reuse existing codes as well.