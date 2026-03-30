#!/usr/bin/env python3
import argparse
import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Default pose model path for the OpenCV DNN backend. Passing a `.pt` model
# switches the script to the Ultralytics runtime instead.
MODEL_PATH = "/home/logan/models/yolo11n-pose.onnx"
# COCO-style 17-keypoint layout used by the YOLO pose models this script expects.
KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]
# Skeleton edges used only for the visualization overlay.
SKELETON = [
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
]


def ensure_model(path: str, backend: str) -> None:
    # Fail early with backend-specific guidance so the user knows which model
    # artifact is expected before camera startup begins.
    model_dir = os.path.dirname(path)
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
    if os.path.isfile(path):
        return

    if backend == "ultralytics":
        raise SystemExit(
            f"missing {path}.\n"
            "Download or copy a YOLO pose .pt checkpoint there first. One working path is:\n"
            "  yolo export model=yolo11n-pose.pt format=onnx opset=12 imgsz=640"
        )

    raise SystemExit(
        f"missing {path}.\n"
        "Export a YOLO pose ONNX model there first. One working path is:\n"
        "  python3 -m pip install --user ultralytics\n"
        "  yolo export model=yolo11n-pose.pt format=onnx opset=12 imgsz=640\n"
        f"  mv yolo11n-pose.onnx {path}"
    )


def infer_backend(model_path: str, backend: str) -> str:
    # In auto mode, `.pt` means Ultralytics and anything else is treated as an
    # ONNX graph for OpenCV DNN.
    if backend != "auto":
        return backend
    if model_path.endswith(".pt"):
        return "ultralytics"
    return "opencv"


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def csi_pipeline(width: int, height: int, fps: int, sensor_id: int) -> str:
    # Jetson CSI capture path: Argus -> NVMM -> BGR frames for OpenCV.
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM), width=(int){width}, height=(int){height}, "
        f"framerate=(fraction){fps}/1, format=(string)NV12 ! "
        "nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink drop=true max-buffers=1 sync=false"
    )


def letterbox(frame: np.ndarray, size: int) -> Tuple[np.ndarray, float, float, float]:
    # Resize with preserved aspect ratio and remember the scale/padding so the
    # model-space outputs can be mapped back onto original frame coordinates.
    h, w = frame.shape[:2]
    scale = min(size / w, size / h)
    resized_w = int(round(w * scale))
    resized_h = int(round(h * scale))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - resized_w) / 2.0
    pad_y = (size - resized_h) / 2.0
    x0 = int(round(pad_x))
    y0 = int(round(pad_y))
    canvas[y0 : y0 + resized_h, x0 : x0 + resized_w] = resized
    return canvas, scale, pad_x, pad_y


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def point_from_triplet(values: np.ndarray, frame_w: int, frame_h: int, scale: float, pad_x: float,
                       pad_y: float) -> Dict[str, float]:
    # Each keypoint arrives as `(x, y, confidence)` in model-input space.
    x = clamp((float(values[0]) - pad_x) / scale, 0.0, frame_w - 1.0)
    y = clamp((float(values[1]) - pad_y) / scale, 0.0, frame_h - 1.0)
    conf = float(values[2])
    return {"x": round(x, 2), "y": round(y, 2), "conf": round(conf, 6)}


def midpoint(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    return {
        "x": round((a["x"] + b["x"]) * 0.5, 2),
        "y": round((a["y"] + b["y"]) * 0.5, 2),
        "conf": round(min(a["conf"], b["conf"]), 6),
    }


def angle_from_vertical_deg(top: Dict[str, float], bottom: Dict[str, float]) -> float:
    # Positive values mean the torso leans to the camera's right, negative to
    # the left, measured relative to a vertical line.
    dx = bottom["x"] - top["x"]
    dy = bottom["y"] - top["y"]
    return math.degrees(math.atan2(dx, max(dy, 1e-6)))


def distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    return float(math.hypot(b["x"] - a["x"], b["y"] - a["y"]))


def build_pose_metrics(keypoints: Dict[str, Dict[str, float]], bbox: List[float],
                       calibration_baseline_deg: Optional[float]) -> Dict[str, object]:
    # Convert raw keypoints into posture-oriented features that are easier to
    # inspect and later classify than the full landmark set alone.
    metrics: Dict[str, object] = {}
    left_shoulder = keypoints.get("left_shoulder")
    right_shoulder = keypoints.get("right_shoulder")
    left_hip = keypoints.get("left_hip")
    right_hip = keypoints.get("right_hip")
    nose = keypoints.get("nose")

    if left_shoulder and right_shoulder:
        # Chest center is approximated as the midpoint between both shoulders.
        chest_center = midpoint(left_shoulder, right_shoulder)
        metrics["chest_center"] = chest_center
        shoulder_tilt_deg = math.degrees(
            math.atan2(right_shoulder["y"] - left_shoulder["y"], right_shoulder["x"] - left_shoulder["x"])
        )
        metrics["shoulder_tilt_deg"] = round(shoulder_tilt_deg, 3)
    else:
        chest_center = None

    if left_hip and right_hip:
        # Hip center is the torso anchor used with chest center for lean angle.
        hip_center = midpoint(left_hip, right_hip)
        metrics["hip_center"] = hip_center
    else:
        hip_center = None

    if chest_center and hip_center:
        # Torso angle and length are normalized against the detection box so the
        # metric is less sensitive to how close the subject is to the camera.
        torso_angle_deg = angle_from_vertical_deg(chest_center, hip_center)
        bbox_h = max(bbox[3] - bbox[1], 1e-6)
        torso_length_norm = distance(chest_center, hip_center) / bbox_h
        metrics["torso_angle_deg"] = round(torso_angle_deg, 3)
        metrics["torso_length_norm"] = round(torso_length_norm, 6)
        spine_points = []
        # This is only a visual proxy, not a full anatomical spine estimate.
        if nose and nose["conf"] >= 0.2:
            spine_points.append(nose)
        spine_points.append(chest_center)
        spine_points.append(hip_center)
        metrics["spine_proxy"] = spine_points
        if calibration_baseline_deg is not None:
            metrics["lean_delta_deg"] = round(torso_angle_deg - calibration_baseline_deg, 3)

    return metrics


def decode_pose_output(output: np.ndarray, frame_shape: Tuple[int, int], scale: float, pad_x: float,
                       pad_y: float, conf_thres: float, nms_thres: float,
                       keypoint_thres: float) -> List[Dict[str, object]]:
    # OpenCV DNN returns a dense pose tensor. This function filters low-score
    # rows, remaps bbox/keypoint coordinates, and applies NMS.
    if output.ndim == 3:
        output = np.squeeze(output, axis=0)
    if output.ndim != 2:
        raise ValueError(f"unexpected pose output shape: {output.shape}")
    if output.shape[0] < output.shape[1]:
        output = output.transpose()

    frame_h, frame_w = frame_shape[:2]
    boxes: List[List[int]] = []
    scores: List[float] = []
    candidates: List[Dict[str, object]] = []

    for row in output:
        if row.shape[0] < 5 + len(KEYPOINT_NAMES) * 3:
            continue

        cx, cy, bw, bh = row[:4]
        class_score = float(row[4])
        if class_score < conf_thres:
            continue

        x1 = clamp((float(cx) - float(bw) * 0.5 - pad_x) / scale, 0.0, frame_w - 1.0)
        y1 = clamp((float(cy) - float(bh) * 0.5 - pad_y) / scale, 0.0, frame_h - 1.0)
        x2 = clamp((float(cx) + float(bw) * 0.5 - pad_x) / scale, 0.0, frame_w - 1.0)
        y2 = clamp((float(cy) + float(bh) * 0.5 - pad_y) / scale, 0.0, frame_h - 1.0)
        if x2 <= x1 or y2 <= y1:
            continue

        triplets = row[5 : 5 + len(KEYPOINT_NAMES) * 3].reshape(len(KEYPOINT_NAMES), 3)
        # Only keep confident keypoints so downstream metrics don't quietly use
        # weak landmarks.
        keypoints = {
            name: point_from_triplet(triplets[idx], frame_w, frame_h, scale, pad_x, pad_y)
            for idx, name in enumerate(KEYPOINT_NAMES)
            if float(triplets[idx][2]) >= keypoint_thres
        }

        boxes.append([int(round(x1)), int(round(y1)), int(round(x2 - x1)), int(round(y2 - y1))])
        scores.append(class_score)
        candidates.append(
            {
                "score": round(class_score, 6),
                "bbox_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "keypoints": keypoints,
            }
        )

    indices = cv2.dnn.NMSBoxes(boxes, scores, conf_thres, nms_thres)
    if len(indices) == 0:
        return []

    keep = [int(idx[0] if isinstance(idx, (list, tuple, np.ndarray)) else idx) for idx in indices]
    keep.sort(key=lambda idx: candidates[idx]["score"], reverse=True)
    return [candidates[idx] for idx in keep]


def decode_ultralytics_result(result: Any, frame_shape: Tuple[int, int], keypoint_thres: float) -> List[Dict[str, object]]:
    # Ultralytics already performs decode/NMS. Here we just normalize the
    # result object into the same detection schema used by the OpenCV backend.
    boxes = getattr(result, "boxes", None)
    keypoints = getattr(result, "keypoints", None)
    if boxes is None or keypoints is None or boxes.xyxy is None or keypoints.data is None:
        return []

    frame_h, frame_w = frame_shape[:2]
    xyxy = boxes.xyxy.detach().cpu().numpy()
    confs = boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.ones((len(xyxy),), dtype=np.float32)
    kpts = keypoints.data.detach().cpu().numpy()
    detections: List[Dict[str, object]] = []

    for idx, box in enumerate(xyxy):
        x1 = clamp(float(box[0]), 0.0, frame_w - 1.0)
        y1 = clamp(float(box[1]), 0.0, frame_h - 1.0)
        x2 = clamp(float(box[2]), 0.0, frame_w - 1.0)
        y2 = clamp(float(box[3]), 0.0, frame_h - 1.0)
        if x2 <= x1 or y2 <= y1:
            continue

        det_keypoints = {}
        for kpt_idx, name in enumerate(KEYPOINT_NAMES):
            conf = float(kpts[idx][kpt_idx][2])
            if conf < keypoint_thres:
                continue
            det_keypoints[name] = {
                "x": round(clamp(float(kpts[idx][kpt_idx][0]), 0.0, frame_w - 1.0), 2),
                "y": round(clamp(float(kpts[idx][kpt_idx][1]), 0.0, frame_h - 1.0), 2),
                "conf": round(conf, 6),
            }

        detections.append(
            {
                "score": round(float(confs[idx]), 6),
                "bbox_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "keypoints": det_keypoints,
            }
        )

    detections.sort(key=lambda det: det["score"], reverse=True)
    return detections


def draw_point(frame: np.ndarray, point: Dict[str, float], color: Tuple[int, int, int], radius: int) -> None:
    cv2.circle(frame, (int(round(point["x"])), int(round(point["y"]))), radius, color, -1, cv2.LINE_AA)


def draw_line(frame: np.ndarray, a: Dict[str, float], b: Dict[str, float],
              color: Tuple[int, int, int], thickness: int) -> None:
    cv2.line(
        frame,
        (int(round(a["x"])), int(round(a["y"]))),
        (int(round(b["x"])), int(round(b["y"]))),
        color,
        thickness,
        cv2.LINE_AA,
    )


def annotate_pose(frame: np.ndarray, detection: Dict[str, object], baseline_deg: Optional[float]) -> None:
    # Visualization layer for debugging and dataset review. It does not change
    # the metrics that are written to JSONL.
    x1, y1, x2, y2 = [int(round(v)) for v in detection["bbox_xyxy"]]
    keypoints = detection["keypoints"]
    metrics = detection["metrics"]

    cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 220, 40), 2)
    cv2.putText(
        frame,
        f"pose {detection['score']:.2f}",
        (x1, max(24, y1 - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (40, 220, 40),
        2,
        cv2.LINE_AA,
    )

    for a_idx, b_idx in SKELETON:
        a = keypoints.get(KEYPOINT_NAMES[a_idx])
        b = keypoints.get(KEYPOINT_NAMES[b_idx])
        if a and b:
            draw_line(frame, a, b, (255, 180, 50), 2)

    for point in keypoints.values():
        draw_point(frame, point, (30, 180, 255), 4)

    chest = metrics.get("chest_center")
    if chest:
        draw_point(frame, chest, (0, 255, 0), 6)
        cv2.putText(
            frame,
            "chest",
            (int(chest["x"]) + 8, int(chest["y"]) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    hip = metrics.get("hip_center")
    if hip:
        draw_point(frame, hip, (255, 120, 0), 6)

    spine_proxy = metrics.get("spine_proxy", [])
    for idx in range(1, len(spine_proxy)):
        draw_line(frame, spine_proxy[idx - 1], spine_proxy[idx], (255, 0, 255), 3)

    overlay_lines = []
    if "torso_angle_deg" in metrics:
        overlay_lines.append(f"torso={metrics['torso_angle_deg']:.1f}deg")
    if "lean_delta_deg" in metrics:
        overlay_lines.append(f"lean={metrics['lean_delta_deg']:+.1f}deg")
    elif baseline_deg is None:
        overlay_lines.append("lean=uncal")
    if "shoulder_tilt_deg" in metrics:
        overlay_lines.append(f"shoulders={metrics['shoulder_tilt_deg']:.1f}deg")

    for idx, text in enumerate(overlay_lines):
        cv2.putText(
            frame,
            text,
            (x1, min(frame.shape[0] - 10, y2 + 22 + idx * 22)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (220, 255, 220),
            2,
            cv2.LINE_AA,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--backend", choices=["auto", "opencv", "ultralytics"], default="auto")
    parser.add_argument("--device", default="0")
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--sensor-id", type=int, default=0)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf-thres", type=float, default=0.35)
    parser.add_argument("--nms-thres", type=float, default=0.45)
    parser.add_argument("--kpt-thres", type=float, default=0.35)
    parser.add_argument("--calibration-frames", type=int, default=45)
    parser.add_argument("--print-every", type=int, default=15)
    parser.add_argument("--output", default="/home/logan/pose-demo.avi")
    parser.add_argument("--pose-out", default="/home/logan/pose-detections.jsonl")
    args = parser.parse_args()

    backend = infer_backend(args.model, args.backend)
    ensure_model(args.model, backend)

    # Open the Jetson CSI camera through the Argus-backed GStreamer pipeline.
    cap = cv2.VideoCapture(
        csi_pipeline(args.width, args.height, args.fps, args.sensor_id),
        cv2.CAP_GSTREAMER,
    )
    if not cap.isOpened():
        raise SystemExit("failed to open CSI camera through GStreamer")

    if backend == "opencv":
        # OpenCV backend expects an exported pose ONNX graph and manual decode.
        net = cv2.dnn.readNetFromONNX(args.model)
        yolo_model = None
    else:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise SystemExit(
                "ultralytics backend requested but package import failed.\n"
                "Install it with: python3 -m pip install --user ultralytics"
            ) from exc
        # Ultralytics backend handles preprocessing and decode internally.
        yolo_model = YOLO(args.model)
        net = None
    ensure_parent_dir(args.output)
    ensure_parent_dir(args.pose_out)
    writer = cv2.VideoWriter(
        args.output,
        cv2.VideoWriter_fourcc(*"MJPG"),
        min(args.fps, 10),
        (args.width, args.height),
    )

    start = time.time()
    last_report: Dict[str, object] = {}
    baseline_samples: List[float] = []
    baseline_deg: Optional[float] = None

    with open(args.pose_out, "w", encoding="utf-8") as pose_file:
        for frame_idx in range(args.frames):
            ok, frame = cap.read()
            if not ok:
                print("frame read failed")
                break

            if backend == "opencv":
                # Match the exported YOLO pose graph's expected square input,
                # then translate outputs back to original frame coordinates.
                model_input, scale, pad_x, pad_y = letterbox(frame, args.imgsz)
                blob = cv2.dnn.blobFromImage(
                    model_input,
                    scalefactor=1.0 / 255.0,
                    size=(args.imgsz, args.imgsz),
                    mean=(0, 0, 0),
                    swapRB=True,
                    crop=False,
                )
                net.setInput(blob)
                detections = decode_pose_output(
                    net.forward(),
                    frame.shape,
                    scale,
                    pad_x,
                    pad_y,
                    args.conf_thres,
                    args.nms_thres,
                    args.kpt_thres,
                )
            else:
                # Limit live inference to the top detection because this script
                # is currently centered on single-subject posture capture.
                results = yolo_model.predict(
                    source=frame,
                    imgsz=args.imgsz,
                    conf=args.conf_thres,
                    iou=args.nms_thres,
                    device=args.device,
                    verbose=False,
                    max_det=1,
                )
                detections = decode_ultralytics_result(results[0], frame.shape, args.kpt_thres) if results else []

            primary_detection = detections[0] if detections else None
            if primary_detection:
                # Build derived posture metrics on top of raw landmarks.
                primary_detection["metrics"] = build_pose_metrics(
                    primary_detection["keypoints"],
                    primary_detection["bbox_xyxy"],
                    baseline_deg,
                )
                torso_angle = primary_detection["metrics"].get("torso_angle_deg")
                if torso_angle is not None and baseline_deg is None and len(baseline_samples) < args.calibration_frames:
                    # Use the first calibration window to establish the user's
                    # neutral torso angle for the current camera placement.
                    baseline_samples.append(float(torso_angle))
                    if len(baseline_samples) == args.calibration_frames:
                        baseline_deg = float(sum(baseline_samples) / len(baseline_samples))
                        primary_detection["metrics"]["lean_delta_deg"] = round(
                            primary_detection["metrics"]["torso_angle_deg"] - baseline_deg,
                            3,
                        )
                elif torso_angle is not None and baseline_deg is not None:
                    primary_detection["metrics"]["lean_delta_deg"] = round(float(torso_angle) - baseline_deg, 3)

                annotate_pose(frame, primary_detection, baseline_deg)

            # The on-frame status text makes calibration progress visible in the
            # saved review video even without opening the JSONL output.
            status = f"calib={len(baseline_samples)}/{args.calibration_frames}" if baseline_deg is None else f"baseline={baseline_deg:.1f}deg"
            cv2.putText(
                frame,
                status,
                (20, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 220, 255),
                2,
                cv2.LINE_AA,
            )
            writer.write(frame)

            report = {
                "frame": frame_idx,
                "t_wall_s": round(time.time() - start, 6),
                "baseline_deg": round(baseline_deg, 6) if baseline_deg is not None else None,
                "primary_detection": primary_detection,
            }
            # Write one JSON object per frame so later analysis can stream or
            # grep the capture without loading the whole run into memory.
            pose_file.write(json.dumps(report) + "\n")
            last_report = report

            if frame_idx % args.print_every == 0:
                print(
                    f"frame={frame_idx} "
                    f"have_pose={1 if primary_detection else 0} "
                    f"baseline={report['baseline_deg']} "
                    f"primary={primary_detection}"
                )

    elapsed = time.time() - start
    cap.release()
    writer.release()
    print(
        f"done frames={last_report.get('frame', -1) + 1} elapsed={elapsed:.2f}s "
        f"fps={max(last_report.get('frame', -1) + 1, 0) / max(elapsed, 1e-6):.2f} "
        f"out={args.output} pose_out={args.pose_out}"
    )
    print(f"last_report={last_report}")


if __name__ == "__main__":
    main()
