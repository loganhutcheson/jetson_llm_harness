#!/usr/bin/env bash
set -euo pipefail

MODE="cam1"
SRC_DTB=""
BACKUP_DIR="/boot/dtb"
REBOOT=0
BASE_DTB="/boot/tegra234-p3768-0000+p3767-0005-nv-super.dtb"
CAM1_DTB="/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.imx219-c.merged.dtb"
DUAL_DTB="/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.imx219-dual.merged.dtb"
DUAL_OVERLAY="/boot/tegra234-p3767-camera-p3768-imx219-dual.dtbo"

usage() {
  cat <<'EOF'
Usage:
  sudo ./jetson/camera/force_imx219_cam1_dtb.sh [--cam1 | --dual] [--src-dtb PATH] [--backup-dir PATH] [--reboot]

Writes the selected IMX219 DTB into both Jetson kernel-dtb slots.
Backups are written before any partition is overwritten.
Modes:
  --cam1   Use the known-good single-camera CAM1 DTB (default)
  --dual   Use a dual-IMX219 DTB. If the merged DTB does not exist, generate it
           from the stock base DTB plus the official dual IMX219 overlay.
EOF
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
  fi
}

verify_file() {
  local path="$1"
  [[ -f "${path}" ]] || {
    echo "missing file: ${path}" >&2
    exit 1
  }
}

verify_partition() {
  local path="$1"
  [[ -b "${path}" ]] || {
    echo "missing block device: ${path}" >&2
    exit 1
  }
}

verify_dtb_strings() {
  local path="$1"
  if ! strings "${path}" | egrep -qi 'imx219|cam_i2cmux|rbpcv2'; then
    echo "expected IMX219 markers not found in ${path}" >&2
    exit 1
  fi
}

require_tool() {
  local tool="$1"
  command -v "${tool}" >/dev/null 2>&1 || {
    echo "missing required tool: ${tool}" >&2
    exit 1
  }
}

ensure_dual_dtb() {
  if [[ -f "${SRC_DTB}" ]]; then
    return
  fi

  verify_file "${BASE_DTB}"
  verify_file "${DUAL_OVERLAY}"
  require_tool fdtoverlay

  fdtoverlay -i "${BASE_DTB}" -o "${SRC_DTB}" "${DUAL_OVERLAY}"
}

backup_partition() {
  local partition="$1"
  local label="$2"
  local out="${BACKUP_DIR}/${label}.bin"

  dd if="${partition}" of="${out}" bs=4k count=192 status=none
  echo "backup:${out}"
}

write_partition() {
  local src="$1"
  local partition="$2"
  dd if="${src}" of="${partition}" bs=4k conv=fsync status=none
}

inspect_partition() {
  local partition="$1"
  dd if="${partition}" bs=4k count=192 status=none | strings | egrep -i 'imx219|cam_i2cmux|rbpcv2' | sed -n '1,20p'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cam1)
      MODE="cam1"
      shift
      ;;
    --dual)
      MODE="dual"
      shift
      ;;
    --src-dtb)
      [[ $# -ge 2 ]] || {
        echo "missing value for --src-dtb" >&2
        exit 1
      }
      SRC_DTB="$2"
      shift 2
      ;;
    --backup-dir)
      [[ $# -ge 2 ]] || {
        echo "missing value for --backup-dir" >&2
        exit 1
      }
      BACKUP_DIR="$2"
      shift 2
      ;;
    --reboot)
      REBOOT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_root
if [[ -z "${SRC_DTB}" ]]; then
  case "${MODE}" in
    cam1)
      SRC_DTB="${CAM1_DTB}"
      ;;
    dual)
      SRC_DTB="${DUAL_DTB}"
      ensure_dual_dtb
      ;;
    *)
      echo "unsupported mode: ${MODE}" >&2
      exit 1
      ;;
  esac
fi

verify_file "${SRC_DTB}"
verify_dtb_strings "${SRC_DTB}"
mkdir -p "${BACKUP_DIR}"

A_PART="/dev/disk/by-partlabel/A_kernel-dtb"
B_PART="/dev/disk/by-partlabel/B_kernel-dtb"
verify_partition "${A_PART}"
verify_partition "${B_PART}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
echo "mode:${MODE}"
echo "src_dtb:${SRC_DTB}"
echo "backup_dir:${BACKUP_DIR}"
backup_partition "${A_PART}" "A_kernel-dtb.pre_imx219.${STAMP}" >/dev/null
backup_partition "${B_PART}" "B_kernel-dtb.pre_imx219.${STAMP}" >/dev/null

write_partition "${SRC_DTB}" "${A_PART}"
write_partition "${SRC_DTB}" "${B_PART}"

echo "verify:A_kernel-dtb"
inspect_partition "${A_PART}"
echo "verify:B_kernel-dtb"
inspect_partition "${B_PART}"

echo "done: wrote ${SRC_DTB} into A_kernel-dtb and B_kernel-dtb"

if [[ "${REBOOT}" -eq 1 ]]; then
  echo "rebooting"
  reboot
fi
