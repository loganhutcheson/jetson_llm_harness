#!/usr/bin/env python3
import argparse
import os
import time

import cv2
import numpy as np

MODEL_URL = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx"
MODEL_PATH = "/home/logan/models/mobilenetv2-7.onnx"
DEFAULT_LABELS = [
    "/home/logan/jetson-inference/build/aarch64/bin/networks/ilsvrc12_synset_words.txt",
    "/home/logan/jetson-inference/data/networks/ilsvrc12_synset_words.txt",
]


def ensure_model():
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    if os.path.isfile(MODEL_PATH):
        return

    raise SystemExit(
        f"missing {MODEL_PATH}. download it first with:\n"
        f"  wget -O {MODEL_PATH} {MODEL_URL}"
    )


def load_labels():
    for path in DEFAULT_LABELS:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return [line.strip() for line in f]

    raise SystemExit("could not find ImageNet labels file")


def csi_pipeline(width: int, height: int, fps: int) -> str:
    return (
        "nvarguscamerasrc sensor-id=0 ! "
        f"video/x-raw(memory:NVMM), width=(int){width}, height=(int){height}, "
        f"framerate=(fraction){fps}/1, format=(string)NV12 ! "
        "nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink drop=true max-buffers=1 sync=false"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--print-every", type=int, default=15)
    parser.add_argument("--output", default="/home/logan/mobilenetv2-demo.avi")
    args = parser.parse_args()

    ensure_model()
    labels = load_labels()

    cap = cv2.VideoCapture(csi_pipeline(args.width, args.height, args.fps), cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        raise SystemExit("failed to open CSI camera through GStreamer")

    net = cv2.dnn.readNetFromONNX(MODEL_PATH)
    writer = cv2.VideoWriter(
        args.output,
        cv2.VideoWriter_fourcc(*"MJPG"),
        min(args.fps, 10),
        (args.width, args.height),
    )

    start = time.time()
    frames = 0
    last_top5 = None

    while frames < args.frames:
        ok, frame = cap.read()
        if not ok:
            print("frame read failed")
            break

        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1.0 / 127.5,
            size=(224, 224),
            mean=(127.5, 127.5, 127.5),
            swapRB=True,
            crop=True,
        )
        net.setInput(blob)
        output = net.forward()[0]
        exp = np.exp(output - np.max(output))
        probs = exp / exp.sum()
        top_indices = probs.argsort()[-5:][::-1]
        last_top5 = [
            (int(i), float(probs[i]), labels[int(i)] if int(i) < len(labels) else str(int(i)))
            for i in top_indices
        ]

        top1 = last_top5[0]
        text = f"top1: {top1[2][:60]} ({top1[1]:.3f})"
        cv2.putText(
            frame,
            text,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        writer.write(frame)

        if frames % args.print_every == 0:
            print(f"frame={frames} top5={last_top5}")

        frames += 1

    elapsed = time.time() - start
    cap.release()
    writer.release()

    print(f"done frames={frames} elapsed={elapsed:.2f}s fps={frames / max(elapsed, 1e-6):.2f} out={args.output}")
    print(f"last_top5={last_top5}")


if __name__ == "__main__":
    main()
