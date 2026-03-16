----- Jetson Camera Inference Notes -----
This directory documents the first working camera inference path we validated on
the Jetson Orin Nano after the CAM1 IMX219 bring-up.

Date validated:
- 2026-03-15

Hardware / software context:
- Jetson Orin Nano dev kit
- Ubuntu 22.04.5 LTS
- L4T `36.5.0`
- TensorRT `10.3.0`
- CSI camera on `csi://0`

----- What Works -----
Working demo:
- live CSI camera capture through Argus / GStreamer
- frame-by-frame classification with a pre-trained `MobileNetV2` ONNX model
- top-1 class overlay written onto output frames
- annotated output video saved on the Jetson

Validated output on the Jetson:
- `/home/logan/mobilenetv2-demo.avi`

Working repo script:
- `jetson/inference/mobilenetv2_camera_demo.py`

What this proves:
- camera capture is healthy
- Python OpenCV can read the CSI stream
- a modern ONNX model can run against live frames
- results can be rendered and saved for review

What it does not prove:
- object detection
- person tracking
- posture classification
- training on our custom data

----- Why This Path Was Needed -----
We also rebuilt `jetson-inference` on the Jetson and got its native C++ binaries
to compile on this JetPack. However, the stock `jetson-inference` example models
were not the quickest path to a working demo on this machine.

Important compatibility note:
- TensorRT `10.3` on JetPack 6 rejects the older Caffe-based sample models used
  by stock `imagenet` in `jetson-inference`
- result: the `jetson-inference` binaries build, but the default Caffe example
  model path fails at runtime

So the first reliable demo became:
- Argus camera input
- ONNX model
- OpenCV DNN inference

That is a more modern and more transferable stack for future work anyway.

----- Jetson Packages Installed -----
These packages were installed on the Jetson during bring-up:

- `cuda-nvcc-12-6`
- `python3-opencv`
- `python3-libnvinfer`
- `python3-libnvinfer-dev`
- `libnpp-dev-12-6`
- `cuda-libraries-dev-12-6`

Python environment fix applied on the Jetson:
- user-site `numpy` was downgraded from `2.2.6` to `1.26.4`

Why:
- `python3-opencv` on this Jetson was built against NumPy 1.x ABI
- with NumPy 2.x installed in `~/.local`, `cv2` import failed

Command used:
- `python3 -m pip install --user --upgrade 'numpy<2'`

----- How The Demo Works -----
Pipeline:
1. `nvarguscamerasrc` captures frames from the CSI camera.
2. GStreamer converts frames into BGR for OpenCV.
3. OpenCV loads `mobilenetv2-7.onnx`.
4. Each frame is resized / normalized into a `224x224` blob.
5. OpenCV DNN runs classification.
6. The top-1 label is drawn on the frame.
7. Frames are written to an AVI file for inspection.

Camera pipeline string used by the script:
- `nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=(int)1280, height=(int)720, framerate=(fraction)30/1, format=(string)NV12 ! nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert ! video/x-raw, format=(string)BGR ! appsink drop=true max-buffers=1 sync=false`

Model used:
- `MobileNetV2`
- ONNX file: `/home/logan/models/mobilenetv2-7.onnx`

Observed performance during the first run:
- `90` frames in about `7.4s`
- roughly `12 FPS`

Because the camera was pointed at the ceiling, the classifications were mostly
scene-adjacent guesses and not semantically useful. That is expected.

----- How To Run It On The Jetson -----
Copy the repo script to the Jetson or run it from a checkout there.

If the model is missing:
- `mkdir -p ~/models`
- `wget -O ~/models/mobilenetv2-7.onnx https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx`

Run:
- `python3 ~/mobilenetv2_camera_demo.py --frames 300 --output ~/mobilenetv2-demo.avi`

Useful options:
- `--frames 300`
- `--width 1280`
- `--height 720`
- `--fps 30`
- `--print-every 15`
- `--output ~/mobilenetv2-demo.avi`

Expected healthy output:
- terminal logs printing `top5=` every N frames
- a finished video file at the requested output path

----- What To Review Tomorrow -----
If you want to understand this stack quickly, review these in order:

1. `jetson/camera/README.txt`
   Why: this explains how the CSI camera became available at all.

2. `jetson/inference/mobilenetv2_camera_demo.py`
   Why: this is the shortest end-to-end example of capture -> preprocess ->
   inference -> overlay -> save.

3. The GStreamer pipeline in `mobilenetv2_camera_demo.py`
   Why: this is the Jetson-specific part. Understanding `nvarguscamerasrc`,
   `nvvidconv`, and `appsink` will help with every later camera task.

4. OpenCV DNN blob creation in `mobilenetv2_camera_demo.py`
   Why: this is where model-specific input normalization happens.

5. `jetson-inference` notes in this file
   Why: this explains why the stock sample path is not the primary path on this
   JetPack / TensorRT combination.

Questions worth answering as you review:
- Where does the CSI frame become a NumPy array?
- What assumptions does the model make about image size and normalization?
- Which part is Jetson-specific, and which part is generic CV / ML plumbing?
- What would need to change to swap `MobileNetV2` for YOLO?
- What output format would be most useful for collecting a posture dataset?

----- Recommended Next Step -----
The next technical step should be a YOLO-based person or pose pipeline instead
of more work on generic image classification.

Why:
- classification over the whole frame is a weak fit for posture
- posture work wants either:
  - person detection + cropped posture classifier
  - pose/keypoint estimation
  - direct custom classifier on seated-person crops

Practical next move:
- run a YOLO ONNX or TensorRT person detector on the same CSI pipeline
- confirm it finds a seated person when the camera is aimed correctly
- then start saving labeled seated-person images for a custom model

