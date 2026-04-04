#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

backend="${POSTURE_RUNTIME_BACKEND:-ultralytics}"
model="${POSTURE_RUNTIME_MODEL:-/home/logan/models/yolo11n-pose.pt}"
device="${POSTURE_RUNTIME_DEVICE:-0}"
sensor_id="${POSTURE_RUNTIME_SENSOR_ID:-0}"
width="${POSTURE_RUNTIME_WIDTH:-1280}"
height="${POSTURE_RUNTIME_HEIGHT:-720}"
fps="${POSTURE_RUNTIME_FPS:-30}"
frames="${POSTURE_RUNTIME_FRAMES:-0}"
conf_thres="${POSTURE_RUNTIME_CONF_THRES:-0.35}"
nms_thres="${POSTURE_RUNTIME_NMS_THRES:-0.45}"
kpt_thres="${POSTURE_RUNTIME_KPT_THRES:-0.35}"
calibration_frames="${POSTURE_RUNTIME_CALIBRATION_FRAMES:-45}"
print_every="${POSTURE_RUNTIME_PRINT_EVERY:-30}"
posture_model="${POSTURE_RUNTIME_POSTURE_MODEL:-}"
posture_window="${POSTURE_RUNTIME_POSTURE_WINDOW:-20}"
posture_min_frames="${POSTURE_RUNTIME_POSTURE_MIN_FRAMES:-12}"
posture_smoothing="${POSTURE_RUNTIME_POSTURE_SMOOTHING:-0.25}"
oled_status="${POSTURE_RUNTIME_OLED_STATUS:-0}"
oled_i2c_dev="${POSTURE_RUNTIME_OLED_I2C_DEV:-/dev/i2c-7}"
oled_i2c_addr="${POSTURE_RUNTIME_OLED_I2C_ADDR:-0x3c}"
sqlite_db="${POSTURE_RUNTIME_SQLITE_DB:-}"
sqlite_sample_interval="${POSTURE_RUNTIME_SQLITE_SAMPLE_INTERVAL:-5}"
session_name="${POSTURE_RUNTIME_SESSION_NAME:-}"
output_path="${POSTURE_RUNTIME_OUTPUT:-}"
pose_out_path="${POSTURE_RUNTIME_POSE_OUT:-}"

args=(
  python3 -u jetson/inference/pose_camera_demo.py
  --backend "${backend}"
  --model "${model}"
  --device "${device}"
  --sensor-id "${sensor_id}"
  --width "${width}"
  --height "${height}"
  --fps "${fps}"
  --frames "${frames}"
  --conf-thres "${conf_thres}"
  --nms-thres "${nms_thres}"
  --kpt-thres "${kpt_thres}"
  --calibration-frames "${calibration_frames}"
  --print-every "${print_every}"
  --posture-window "${posture_window}"
  --posture-min-frames "${posture_min_frames}"
  --posture-smoothing "${posture_smoothing}"
)

if [[ -n "${posture_model}" ]]; then
  args+=(--posture-model "${posture_model}")
fi

if [[ -n "${sqlite_db}" ]]; then
  args+=(--sqlite-db "${sqlite_db}" --sqlite-sample-interval "${sqlite_sample_interval}")
fi

if [[ -n "${session_name}" ]]; then
  args+=(--session-name "${session_name}")
fi

if [[ "${oled_status}" == "1" || "${oled_status}" == "true" || "${oled_status}" == "TRUE" ]]; then
  args+=(--oled-status --oled-i2c-dev "${oled_i2c_dev}" --oled-i2c-addr "${oled_i2c_addr}")
fi

if [[ -n "${output_path}" ]]; then
  args+=(--output "${output_path}")
else
  args+=(--output "")
fi

if [[ -n "${pose_out_path}" ]]; then
  args+=(--pose-out "${pose_out_path}")
else
  args+=(--pose-out "")
fi

if [[ -n "${POSTURE_RUNTIME_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_args=(${POSTURE_RUNTIME_EXTRA_ARGS})
  args+=("${extra_args[@]}")
fi

echo "[posture-runtime] cwd=${REPO_ROOT}"
echo "[posture-runtime] backend=${backend} model=${model} frames=${frames}"
echo "[posture-runtime] output='${output_path}' pose_out='${pose_out_path}'"
exec "${args[@]}"
