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

## Dual IMX219 Bring-up

Current dual-camera setup on this Jetson:
- CSI_0 / CAM0: IMX219 IR camera with IR LED array
- CSI_1 / CAM1: regular IMX219 camera
- the runtime kernel DTB must be dual-capable before the second camera will ever probe
- on this Jetson, selecting the dual overlay in `extlinux.conf` was not enough by itself
- the final working fix was generating a merged dual DTB and writing it into both `A_kernel-dtb` and `B_kernel-dtb`

Why this mattered:
- with the old CAM1-only runtime DTB, the live `rbpcv2_imx219_a@10` node stayed `disabled`
- after the dual merged DTB was written into the runtime partitions, the kernel began probing both sensors
- healthy dual probe looks like:
  - `imx219 9-0010 ... bound`
  - `imx219 10-0010 ... bound`

Useful paths and mappings:
- stock base DTB:
  - `/boot/tegra234-p3768-0000+p3767-0005-nv-super.dtb`
- official dual overlay:
  - `/boot/tegra234-p3767-camera-p3768-imx219-dual.dtbo`
- generated dual merged DTB:
  - `/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.imx219-dual.merged.dtb`
- live DT camera nodes:
  - CSI_0: `/sys/firmware/devicetree/base/bus@0/cam_i2cmux/i2c@0/rbpcv2_imx219_a@10`
  - CSI_1: `/sys/firmware/devicetree/base/bus@0/cam_i2cmux/i2c@1/rbpcv2_imx219_c@10`
- live camera-platform mapping:
  - `module0 -> rbpcv2_imx219_a@10 -> CSI_0`
  - `module1 -> rbpcv2_imx219_c@10 -> CSI_1`

Validated dual-DTB workflow on the Jetson:

```bash
sudo ./jetson/camera/force_imx219_cam1_dtb.sh --dual --reboot
```

Post-reboot validation:

```bash
ls -l /dev/video* /dev/media* 2>/dev/null
sudo dmesg | egrep -i 'imx219|camera|nvcsi|vi5|csi'
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/csi0_test.jpg
gst-launch-1.0 -e nvarguscamerasrc sensor-id=1 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/csi1_test.jpg
file /tmp/csi0_test.jpg /tmp/csi1_test.jpg
```

Healthy dual-camera indicators:
- `/dev/video0` and `/dev/video1` both exist on this Jetson
- both IMX219 sensors bind in `dmesg`
- `sensor-id=0` still capture succeeds
- `sensor-id=1` still capture succeeds

Important Argus note:
- with the old single-CAM1 runtime DTB, `sensor-id=0` referred to the only active camera on CSI_1
- with the working dual merged DTB, Argus ordering follows the live camera-platform modules:
  - `sensor-id=0` -> CSI_0 / IMX219 A / current IR camera
  - `sensor-id=1` -> CSI_1 / IMX219 C / current regular camera

IR-camera-specific notes:
- the IR IMX219 is not a thermal camera
- it is a normal image sensor that can see near-IR illumination from the LED array
- in darkness it acts like a camera plus a less-visible IR flashlight
- if the image is only haze or noise, check lens focus before assuming the sensor path is broken
- these modules are manual-focus; some lenses are thread-locked from the factory

Validated CSI_0 IR still capture:

```bash
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/ir_cam_still.jpg
file /tmp/ir_cam_still.jpg
```

Validated CSI_0 IR live stream to Mac:

Mac receiver:

```bash
ffplay -fflags nobuffer -flags low_delay -framedrop 'udp://0.0.0.0:5008?listen=1&fifo_size=1000000&overrun_nonfatal=1'
```

Jetson sender:

```bash
printf 'Lablab123\n' | sudo -S systemctl restart nvargus-daemon
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1,format=NV12' ! nvvidconv ! 'video/x-raw,format=I420,width=640,height=360' ! videorate ! 'video/x-raw,framerate=10/1' ! x264enc tune=zerolatency speed-preset=ultrafast bitrate=1000 key-int-max=10 byte-stream=true ! h264parse config-interval=1 ! mpegtsmux ! udpsink host=192.168.8.192 port=5008 sync=false async=false
```

Focus helpers for the manual-focus IR module:

```bash
gst-launch-1.0 nvarguscamerasrc sensor-id=0 ! 'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1' ! nvvidconv ! xvimagesink
watch -n 0.5 "gst-launch-1.0 -q nvarguscamerasrc sensor-id=0 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/ir_focus.jpg && file /tmp/ir_focus.jpg"
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
