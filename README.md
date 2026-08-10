# FPGA-Accelerated Object Tracking

An FPGA-based hardware accelerator for real-time object detection and tracking, developed as a semester project at the **University of Moratuwa, Department of Computer Science and Engineering**.

The project explores how computationally intensive parts of an object tracking pipeline can be implemented directly in FPGA hardware to achieve lower latency and higher energy efficiency compared with a software-only implementation.

## Project Overview

Modern object detection and tracking algorithms can be computationally demanding, particularly when deployed on resource-constrained embedded platforms. This project investigates a hardware-accelerated approach in which selected stages of the vision pipeline are implemented using **SystemVerilog RTL** and executed directly on an FPGA.

The initial implementation focuses on establishing a complete hardware video-processing pipeline and progressively introducing hardware acceleration for object tracking.

### Current Pipeline

```text
FPV Camera
    │
    ▼
ADV7180 Video Decoder
    │
    ▼
FPGA Video Input
    │
    ▼
Image Processing / Feature Extraction
    │
    ▼
Object Detection / Matching
    │
    ▼
Object Tracking
    │
    ▼
VGA Display
```

## Objectives

* Develop a real-time FPGA-based object tracking pipeline.
* Interface an analog camera with the FPGA through the onboard **ADV7180 video decoder**.
* Implement computationally intensive vision operations using RTL hardware.
* Explore hardware architectures suitable for low-latency image processing.
* Reduce dependence on a general-purpose processor for the vision pipeline.
* Evaluate the performance and resource requirements of the hardware implementation.
* Investigate architectures that can later be extended to neural-network-based object detection.

## Hardware

The current implementation targets the **Terasic DE2-115 development board**.

Key hardware components include:

* FPGA: Intel/Altera Cyclone IV E
* Analog video input through the onboard ADV7180 video decoder
* VGA output
* External FPV camera
* On-board memory and FPGA resources for image processing

## Software & Development Tools

* SystemVerilog / Verilog
* Intel Quartus Prime
* ModelSim / QuestaSim
* Python for experimentation and algorithm validation
* Git
* Linux development environment

## Hardware Architecture

The accelerator is being designed as a modular RTL system. Major components include:

* Video input interface
* Video timing and synchronization
* Image buffers
* Feature extraction / matching units
* Object tracking logic
* Control unit
* Memory interfaces
* VGA output interface

The design is being developed with hardware parallelism in mind, allowing independent operations to execute concurrently rather than following the sequential execution model of a CPU.

## Development Approach

The project is being developed incrementally.

### 1. Video Input

The first stage is to establish a reliable camera-to-FPGA pipeline using the DE2-115's analog video input and ADV7180 decoder.

### 2. Video Output

Decoded frames are processed by the FPGA and displayed through VGA. This provides a simple way to verify that the complete video path is functioning correctly.

### 3. Basic Tracking

A lightweight object matching/tracking algorithm is implemented first to establish a functional hardware tracking pipeline before introducing more computationally intensive models.

### 4. Hardware Acceleration

The computationally intensive sections of the algorithm are converted into RTL hardware blocks. The architecture is optimized for:

* Parallel execution
* Pipelining
* Reduced memory access
* Deterministic latency
* Efficient FPGA resource utilization

### 5. Evaluation

The final implementation will be evaluated based on:

* Processing latency
* Frames per second
* FPGA resource utilization
* Memory requirements
* Accuracy of tracking
* Hardware/software performance comparison

## Project Status

The project is currently in the **hardware implementation and integration stage**.

Current work includes:

* [x] Initial FPGA development environment setup
* [x] Investigation of the DE2-115 video input architecture
* [x] Identification of the ADV7180 configuration requirements
* [ ] Complete camera-to-FPGA video pipeline
* [ ] VGA output integration
* [ ] Hardware implementation of the initial tracking algorithm
* [ ] Integration of tracking with the live video stream
* [ ] FPGA resource and performance evaluation
* [ ] Final optimization

## Future Work

Depending on the resource requirements and performance of the initial implementation, the project may be extended toward neural-network-based object detection and tracking.

Potential future directions include:

* Lightweight CNN acceleration
* YOLO-based object detection
* Template matching acceleration
* Systolic-array-based neural-network computation
* Hardware/software co-design
* Reduced-precision arithmetic
* Multi-object tracking
* Fully pipelined streaming image processing

<!-- ## Repository Structure

```text
.
├── rtl/              # SystemVerilog RTL modules
├── sim/              # Simulation files and testbenches
├── constraints/      # FPGA pin and timing constraints
├── software/         # Python/software reference implementations
├── docs/             # Project documentation
└── README.md
``` -->

## Academic Project

**Semester Project**
Department of Computer Science and Engineering
University of Moratuwa, Sri Lanka

The project investigates the design and implementation of a practical FPGA-based vision accelerator, with emphasis on **RTL design, hardware architecture, parallel processing, and real-time embedded vision**.
