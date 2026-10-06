#!/bin/bash
# P3b part A: speed sweeps, S-3x8 then ZSAD, both crop modes
cd ~/Documents/Low-Latency-Visual-Object-Tracking/hardware/ethernet
set -x
make program-s3x8 && sleep 5
make speed TRACKER=s3x8 CROP=server
make speed TRACKER=s3x8 CROP=fpga
make program-zsad && sleep 5
make speed TRACKER=zsad CROP=server
make speed TRACKER=zsad CROP=fpga
make program-s3x8
echo ALL_DONE
