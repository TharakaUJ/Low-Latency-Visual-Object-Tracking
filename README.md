# FPGA-Based Real-Time Object Tracking

A real-time visual tracking system implemented on an **Altera Cyclone IV FPGA** using the **DE2-115 development board**.

The project aims to investigate how object tracking algorithms can be implemented and accelerated directly in FPGA hardware, starting from a lightweight template-matching approach and gradually exploring more adaptive tracking techniques.

## Current Architecture

The current system processes the luminance (`Y`) component of a video stream captured through the DE2-115's video input pipeline.

```text
                Camera
                   │
                   ▼
            ADV7180 Decoder
                   │
                   ▼
              Y (8-bit)
                   │
                   ▼
        ┌─────────────────────┐
        │  Template Matcher   │
        │      (FPGA)         │
        └─────────────────────┘
                   │
                   ▼
          Bounding Box / Position
                   │
                   ▼
              VGA Output
```

The template matcher operates directly on the incoming video stream and produces the estimated position of the tracked object. The resulting bounding box can then be overlaid on the video output.

## Development Plan

The project is being developed incrementally:

1. **Video Input**

   * Capture a stable video stream from the analog camera.
   * Extract and process the 8-bit luminance component.

2. **Basic Template Matching**

   * Implement a small template-based tracker in FPGA hardware.
   * Develop the required line buffers, template storage, and matching logic.
   * Produce the best-matching position for each frame.

3. **Video Overlay**

   * Generate a bounding box around the detected object.
   * Display the tracking result through the VGA output.

4. **Host ↔ FPGA Communication**

   * Add a communication interface between the FPGA and a host computer.
   * Allow operations such as initializing/updating the template and transferring tracking information.

5. **Adaptive Tracking**

   * Investigate methods for updating the template as the object changes.
   * Compare different lightweight tracking strategies in terms of accuracy, hardware cost, and performance.

6. **Hardware Optimization**

   * Explore parallelism, pipelining, memory organization, and other FPGA-specific optimizations to improve real-time performance.

## Project Goal

The overall goal is to develop a **hardware-accelerated real-time object tracking pipeline** and evaluate how different tracking approaches trade off **tracking accuracy, computational complexity, memory usage, and FPGA resource utilization**.

