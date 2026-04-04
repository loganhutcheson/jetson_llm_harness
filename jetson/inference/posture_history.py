#!/usr/bin/env python3
import json
import os
import socket
import sqlite3
import time
from typing import Dict, Optional


def posture_value(label: str) -> Optional[float]:
    if label == "good":
        return 1.0
    if label == "okay":
        return 0.0
    if label == "bad":
        return -1.0
    return None


class PostureHistoryStore:
    def __init__(self, db_path: str, sample_interval_s: float, session_name: str) -> None:
        self.db_path = db_path
        self.sample_interval_s = max(float(sample_interval_s), 1.0)
        self.session_name = session_name.strip()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._initialize_schema()
        self.session_id: Optional[int] = None
        self.last_sample_ts: Optional[float] = None
        self.last_status_label: Optional[str] = None

    def _initialize_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                host TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                backend TEXT,
                model_path TEXT,
                posture_model_path TEXT,
                sensor_id INTEGER,
                width INTEGER,
                height INTEGER,
                fps INTEGER,
                config_json TEXT NOT NULL,
                total_frames INTEGER DEFAULT 0,
                last_status_label TEXT
            );

            CREATE TABLE IF NOT EXISTS posture_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts_unix REAL NOT NULL,
                frame_index INTEGER NOT NULL,
                status_label TEXT NOT NULL,
                posture_label TEXT,
                posture_confidence REAL,
                posture_value REAL,
                pose_detected INTEGER NOT NULL,
                pose_score REAL,
                good_probability REAL,
                okay_probability REAL,
                bad_probability REAL,
                shoulder_tilt_deg REAL,
                torso_angle_deg REAL,
                lean_delta_deg REAL,
                oled_status_text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posture_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts_unix REAL NOT NULL,
                frame_index INTEGER NOT NULL,
                status_label TEXT NOT NULL,
                posture_label TEXT,
                posture_confidence REAL,
                oled_status_text TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_posture_samples_ts
            ON posture_samples(ts_unix);

            CREATE INDEX IF NOT EXISTS idx_posture_samples_session_ts
            ON posture_samples(session_id, ts_unix);

            CREATE INDEX IF NOT EXISTS idx_posture_events_session_ts
            ON posture_events(session_id, ts_unix);
            """
        )
        self.conn.commit()

    def start_session(self, args: Dict[str, object]) -> int:
        started_at = time.time()
        config_json = json.dumps(args, sort_keys=True)
        cursor = self.conn.execute(
            """
            INSERT INTO sessions (
                session_name, host, pid, started_at, backend, model_path,
                posture_model_path, sensor_id, width, height, fps, config_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_name or "posture-runtime",
                socket.gethostname(),
                os.getpid(),
                started_at,
                str(args.get("backend", "")),
                str(args.get("model", "")),
                str(args.get("posture_model", "")),
                int(args.get("sensor_id", 0)),
                int(args.get("width", 0)),
                int(args.get("height", 0)),
                int(args.get("fps", 0)),
                config_json,
            ),
        )
        self.conn.commit()
        self.session_id = int(cursor.lastrowid)
        return self.session_id

    def record_report(self, report: Dict[str, object]) -> None:
        if self.session_id is None:
            raise RuntimeError("session has not been started")

        ts_unix = time.time()
        frame_index = int(report.get("frame", -1))
        primary_detection = report.get("primary_detection")
        posture_prediction = report.get("posture_prediction")
        oled_status_text = str(report.get("oled_status_text", "not found"))
        status_label = oled_status_text.replace(" ", "_")
        pose_detected = 1 if primary_detection else 0
        posture_label = posture_prediction.get("label") if posture_prediction else None
        posture_confidence = posture_prediction.get("confidence") if posture_prediction else None
        probabilities = posture_prediction.get("probabilities", {}) if posture_prediction else {}
        metrics = primary_detection.get("metrics", {}) if primary_detection else {}
        pose_score = primary_detection.get("score") if primary_detection else None

        should_write_sample = self.last_sample_ts is None or (ts_unix - self.last_sample_ts) >= self.sample_interval_s
        status_changed = status_label != self.last_status_label

        if should_write_sample or status_changed:
            self.conn.execute(
                """
                INSERT INTO posture_samples (
                    session_id, ts_unix, frame_index, status_label, posture_label,
                    posture_confidence, posture_value, pose_detected, pose_score,
                    good_probability, okay_probability, bad_probability,
                    shoulder_tilt_deg, torso_angle_deg, lean_delta_deg, oled_status_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.session_id,
                    ts_unix,
                    frame_index,
                    status_label,
                    posture_label,
                    posture_confidence,
                    posture_value(status_label),
                    pose_detected,
                    pose_score,
                    probabilities.get("good"),
                    probabilities.get("okay"),
                    probabilities.get("bad"),
                    metrics.get("shoulder_tilt_deg"),
                    metrics.get("torso_angle_deg"),
                    metrics.get("lean_delta_deg"),
                    oled_status_text,
                ),
            )
            self.last_sample_ts = ts_unix

        if status_changed:
            self.conn.execute(
                """
                INSERT INTO posture_events (
                    session_id, ts_unix, frame_index, status_label,
                    posture_label, posture_confidence, oled_status_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.session_id,
                    ts_unix,
                    frame_index,
                    status_label,
                    posture_label,
                    posture_confidence,
                    oled_status_text,
                ),
            )
            self.last_status_label = status_label

        if should_write_sample or status_changed:
            self.conn.commit()

    def finish_session(self, total_frames: int, last_status_label: str) -> None:
        if self.session_id is None:
            return
        self.conn.execute(
            """
            UPDATE sessions
            SET ended_at = ?, total_frames = ?, last_status_label = ?
            WHERE id = ?
            """,
            (time.time(), total_frames, last_status_label, self.session_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
