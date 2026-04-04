# Posture System Setup

This document covers the full persistent posture system on the Jetson:

- always-on posture runtime service
- SQLite history database
- web dashboard service
- developer flow for stopping the service and running manually

## What Runs

There are two long-running services:

1. `posture-runtime.service`
   - captures the CSI camera
   - runs pose inference and posture classification
   - updates the OLED/LCD status text
   - writes posture history into SQLite

2. `posture-dashboard.service`
   - serves the SQLite history over HTTP
   - renders trend views and analytics

## Recommended Persistent Paths

Do not rely on `/tmp` for the long-term system. Use a persistent directory:

```bash
mkdir -p /home/logan/posture
```

Recommended files:

```bash
/home/logan/posture/posture_classifier.json
/home/logan/posture/posture_history.sqlite3
```

If the trained classifier is still only in `/tmp`, copy it once:

```bash
cp /tmp/posture_classifier.json /home/logan/posture/posture_classifier.json
```

## Install The Runtime Service

From the repo on the Jetson:

```bash
cd /home/logan/jetson-runtime
./jetson/services/install_posture_runtime_service.sh
```

Edit the runtime env file:

```bash
sudo nano /etc/default/posture-runtime
```

Recommended runtime settings:

```bash
POSTURE_RUNTIME_BACKEND=ultralytics
POSTURE_RUNTIME_MODEL=/home/logan/models/yolo11n-pose.pt
POSTURE_RUNTIME_DEVICE=0
POSTURE_RUNTIME_SENSOR_ID=0
POSTURE_RUNTIME_WIDTH=1280
POSTURE_RUNTIME_HEIGHT=720
POSTURE_RUNTIME_FPS=30
POSTURE_RUNTIME_FRAMES=0
POSTURE_RUNTIME_POSTURE_MODEL=/home/logan/posture/posture_classifier.json
POSTURE_RUNTIME_OLED_STATUS=1
POSTURE_RUNTIME_OLED_I2C_DEV=/dev/i2c-7
POSTURE_RUNTIME_OLED_I2C_ADDR=0x3c
POSTURE_RUNTIME_SQLITE_DB=/home/logan/posture/posture_history.sqlite3
POSTURE_RUNTIME_SQLITE_SAMPLE_INTERVAL=5
POSTURE_RUNTIME_SESSION_NAME=always-on
POSTURE_RUNTIME_OUTPUT=
POSTURE_RUNTIME_POSE_OUT=
```

Enable and start it:

```bash
sudo systemctl enable --now posture-runtime.service
```

Check status:

```bash
systemctl status posture-runtime.service
journalctl -u posture-runtime.service -n 50 --no-pager
```

## Install The Dashboard Service

Install:

```bash
cd /home/logan/jetson-runtime
./jetson/services/install_posture_dashboard_service.sh
```

Edit the dashboard env file:

```bash
sudo nano /etc/default/posture-dashboard
```

Recommended settings:

```bash
POSTURE_DASHBOARD_DB=/home/logan/posture/posture_history.sqlite3
POSTURE_DASHBOARD_HOST=0.0.0.0
POSTURE_DASHBOARD_PORT=8787
```

Enable and start it:

```bash
sudo systemctl enable --now posture-dashboard.service
```

Check status:

```bash
systemctl status posture-dashboard.service
journalctl -u posture-dashboard.service -n 50 --no-pager
```

Open the dashboard from another machine:

```bash
http://jetson.local:8787/
```

## Developer Flow

To stop the always-on runtime and run manually:

```bash
sudo systemctl stop posture-runtime.service
cd /home/logan/jetson-runtime
./jetson/services/run_posture_runtime.sh
```

To run the dashboard manually:

```bash
sudo systemctl stop posture-dashboard.service
cd /home/logan/jetson-runtime
./jetson/services/run_posture_dashboard.sh
```

To return to service mode:

```bash
sudo systemctl start posture-runtime.service
sudo systemctl start posture-dashboard.service
```

## Useful Checks

Confirm OLED presence:

```bash
i2cdetect -y -r 7
python3 jetson/inference/oled_hello.py --i2c-dev /dev/i2c-7 --i2c-addr 0x3c --text "hello world"
```

Confirm the database is being updated:

```bash
sqlite3 /home/logan/posture/posture_history.sqlite3 'select count(*) from posture_samples;'
sqlite3 /home/logan/posture/posture_history.sqlite3 'select ts_unix, oled_status_text from posture_samples order by id desc limit 10;'
```

Confirm the dashboard API:

```bash
curl http://127.0.0.1:8787/api/summary?hours=24
curl http://127.0.0.1:8787/api/analytics?hours=24
```

## Notes

- `POSTURE_RUNTIME_FRAMES=0` means run forever.
- Empty `POSTURE_RUNTIME_OUTPUT` and `POSTURE_RUNTIME_POSE_OUT` disable AVI and JSONL recording, which is usually what you want for the always-on deployment.
- The persistent history lives in SQLite. JSONL is still useful for temporary experiments, not for the always-on path.
- On this Jetson, the working OLED bus for header I2C is `/dev/i2c-7`, even though the header is referred to as `I2C_1`.
