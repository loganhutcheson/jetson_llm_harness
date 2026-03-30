# Developer Notes

This document holds the operational notes, bring-up details, and current pose-capture workflow that used to live in the root README.

## Repo Layout

- `src/`: main runtime, IMU integration, OLED support, buzzer support
- `jetson/camera/`: Jetson CAM1 IMX219 bring-up helper
- `jetson/inference/`: live pose capture scripts for the Jetson CSI camera
- `scripts/`: small bring-up helpers
- `experiments/`: local experiments kept outside the main runtime path

## Build

```bash
cmake -S . -B build
cmake --build build -j
./build/jetson_runtime
```

On the Jetson, install `cmake` once with:

```bash
sudo apt-get install -y cmake
```

If `cmake` is unavailable on the Jetson, a direct compile still works:

```bash
/usr/bin/c++ -std=c++20 -O2 -Isrc src/main.cpp -pthread -o jetson_runtime
```

## Runtime Configuration

Default behavior uses the synthetic IMU path so local builds still run off-device.

### Real IMU

```bash
JETSON_IMU_SOURCE=mpu6050
JETSON_IMU_ENABLE=1
JETSON_IMU_I2C_DEV=/dev/i2c-7
JETSON_IMU_I2C_ADDR=0x68
```

Notes:
- On the Jetson Orin Nano dev kit, header pins `3/5` map to Linux I2C bus `/dev/i2c-7`.
- With `AD0` tied to ground, the expected MPU-6050 address is `0x68`.
- `i2cdetect -y -r 7` is the fastest sanity check for that bus.

### OLED

```bash
JETSON_OLED_ENABLE=1
JETSON_OLED_I2C_DEV=/dev/i2c-7
JETSON_OLED_I2C_ADDR=0x3c
```

Notes:
- The current 128x64 OLED module is on `/dev/i2c-7` at `0x3c`.
- The working path here is the repo's raw C++ userspace OLED driver.

### Buzzer

```bash
JETSON_BUZZER_ENABLE=1
JETSON_BUZZER_PIN=7
JETSON_BUZZER_ACTIVE_LOW=1
```

Suggested wiring:
- buzzer `I/O` -> physical pin `7`
- buzzer `GND` -> physical pin `14`
- buzzer `VCC` -> physical pin `17`

### Full Jetson Runtime Example

```bash
JETSON_IMU_SOURCE=mpu6050 \
JETSON_IMU_ENABLE=1 \
JETSON_OLED_ENABLE=1 \
JETSON_BUZZER_ENABLE=1 \
JETSON_BUZZER_PIN=7 \
JETSON_BUZZER_ACTIVE_LOW=1 \
./build/jetson_runtime
```

Healthy startup indicators:
- `[main] IMU source=mpu6050(/dev/i2c-7, addr=0x68)`
- `[main] oled enabled=1`
- `[main] buzzer enabled=1 pin=7`

Healthy completion indicator:
- `[LCD]`
- `  RUN COMPLETE`

## Jetson Camera Bring-Up

The repo's camera path uses the Jetson CSI camera through Argus / GStreamer.

Relevant files:
- `jetson/camera/force_imx219_cam1_dtb.sh`
- `jetson/inference/pose_camera_demo.py`

CAM1 IMX219 bring-up summary:
- the working module is a Sony IMX219-compatible camera on CAM1
- on this Jetson, the live runtime DTB came from the `A_kernel-dtb` / `B_kernel-dtb` partitions
- a correct-looking `/boot` DTB was not enough by itself
- the fix was writing the merged CAM1 DTB into both runtime DTB partitions and rebooting

Healthy camera indicators:
- `imx219 9-0010` binds on CAM1
- `/dev/video0` exists
- Argus still capture succeeds

Recommended validation on the Jetson:

```bash
sudo ./jetson/camera/force_imx219_cam1_dtb.sh --reboot
find /sys/firmware/devicetree/base -iname '*imx219*' -o -iname '*cam_i2cmux*'
ls -l /dev/video* /dev/media* 2>/dev/null
sudo dmesg | egrep -i 'imx219|camera|nvcsi|vi5|csi'
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/imx219_cam1_test.jpg
file /tmp/imx219_cam1_test.jpg
```

## Pose Capture

The active vision path in this repo is `jetson/inference/pose_camera_demo.py`.

What it does:
- opens the CSI camera through Argus / GStreamer
- runs YOLO pose inference
- writes annotated video
- writes one JSON object per frame to a JSONL file
- derives posture-oriented metrics from keypoints, including:
  - chest center
  - hip center
  - shoulder tilt
  - torso angle
  - lean delta after calibration
  - a simple spine proxy for overlay

Backends:
- OpenCV DNN with an exported pose ONNX model
- Ultralytics with a `.pt` pose model

Current practical recommendation on the Jetson:
- prefer the Ultralytics backend for live pose inference
- OpenCV DNN on this Jetson's `cv2 4.5.4` was not reliable for the exported pose ONNX models

Example live capture:

```bash
python3 jetson/inference/pose_camera_demo.py \
  --backend ultralytics \
  --model ~/models/yolov8n-pose.pt \
  --frames 18000 \
  --output ~/posture-data/good/good_001.avi \
  --pose-out ~/posture-data/good/good_001.jsonl
```

Healthy runtime indicators:
- CSI camera opens successfully on `sensor-id=0`
- `primary_detection` is usually not `null`
- annotated output video is written
- JSONL output contains keypoints and derived metrics

## Live Streaming To Mac

This Jetson can stream its CSI camera live to a Mac over UDP without using the
repo's Python inference scripts.

Working path on this machine:
- camera input: `nvarguscamerasrc`
- resize / colorspace: `nvvidconv`
- frame-rate limit: `videorate`
- H.264 encode: `x264enc`
- container: `mpegtsmux`
- transport: `udpsink`

Why this path:
- `nvv4l2h264enc` was not available on the tested Jetson
- a direct `nvvidconv -> x264enc` link failed until an explicit `I420` raw stage plus `videorate` stage was inserted
- `ffplay` on the Mac can receive the stream directly, so VLC is optional

Mac receiver:

```bash
ffplay -fflags nobuffer -flags low_delay -framedrop 'udp://@:5002?fifo_size=1000000&overrun_nonfatal=1'
```

Quick local `ffplay` sanity check on the Mac:

```bash
ffplay -f lavfi -i testsrc=size=640x360:rate=30
```

Jetson sender template:

```bash
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 ! 'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1,format=NV12' ! nvvidconv ! 'video/x-raw,format=I420,width=640,height=360' ! videorate ! 'video/x-raw,framerate=15/1' ! x264enc tune=zerolatency speed-preset=ultrafast bitrate=1500 key-int-max=15 ! h264parse ! mpegtsmux ! udpsink host=<mac-ip> port=5002 sync=false async=false
```

Validated sender example:

```bash
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 ! 'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1,format=NV12' ! nvvidconv ! 'video/x-raw,format=I420,width=640,height=360' ! videorate ! 'video/x-raw,framerate=15/1' ! x264enc tune=zerolatency speed-preset=ultrafast bitrate=1500 key-int-max=15 ! h264parse ! mpegtsmux ! udpsink host=192.168.8.192 port=5002 sync=false async=false
```

Usage notes:
- start the Mac receiver first, then start the Jetson sender
- if `ffplay` prints `nan` counters forever, it is waiting for packets and no usable video is arriving yet
- if the Mac reports `Address already in use`, another process already owns that UDP port; either kill it or switch to another port
- if `jetson.local` does not resolve or SSH cleanly from the Mac, use the Jetson's numeric LAN IP instead

Useful Mac cleanup commands:

```bash
pkill ffplay
lsof -nP -iUDP:5002
```

VLC fallback:
- open `udp://@:5002`

## Dataset Guidance

If your goal is posture classification from this camera angle, the current intended dataset split is:

- `good`: 10 minutes
- `okay`: 10 minutes
- `bad`: 10 minutes

Recommended recording layout:

```bash
mkdir -p ~/posture-data/good ~/posture-data/okay ~/posture-data/bad
```

Recommended practice:
- keep the camera physically fixed
- keep lighting stable
- keep the chair and monitor in normal positions
- record separate files per label
- include natural movement instead of freezing

Quick validation after each recording:

```bash
sed -n '1,3p' ~/posture-data/good/good_001.jsonl
tail -n 1 ~/posture-data/good/good_001.jsonl
```

The key thing to verify is that `primary_detection` is present most of the time.
