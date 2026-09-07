# Firmware Build

See the root [README](../../README.md) for the project overview.

This folder holds the Nios V firmware flow. The source file is in [src/main.c](src/main.c).

Use the local makefile when you are in the Nios V toolchain environment:

```bash
make bsp
make app
make download
```

The equivalent direct commands are:

```bash
niosv-bsp -c --type=hal --sopcinfo=$HOME/Documents/Low-Latency-Visual-Object-Tracking/hardware/rtl/soc_system/microcontroller.sopcinfo $HOME/Documents/Low-Latency-Visual-Object-Tracking/hardware/software/bsp/settings.bsp
niosv-app --app-dir=$HOME/Documents/Low-Latency-Visual-Object-Tracking/hardware/software/app --bsp-dir=$HOME/Documents/Low-Latency-Visual-Object-Tracking/hardware/software/bsp --srcs=$HOME/Documents/Low-Latency-Visual-Object-Tracking/hardware/software/src/main.c
niosv-download -g app.elf -i 0 -d 0 -c 1
```

The `app/` and `bsp/` directories are generated outputs and are ignored in git.