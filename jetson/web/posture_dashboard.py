#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import sqlite3
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

ACTIVE_SAMPLE_WINDOW_S = 600.0


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Posture Trends</title>
  <style>
    :root {
      --bg: #0d1b1e;
      --panel: #13272b;
      --ink: #f3f5ef;
      --muted: #8ca3a6;
      --good: #79c36a;
      --okay: #f0c35b;
      --bad: #e16b5c;
      --missing: #60757d;
      --grid: rgba(255,255,255,0.08);
    }
    body { margin: 0; background: radial-gradient(circle at top, #18353a 0, var(--bg) 55%); color: var(--ink); font: 16px/1.4 Georgia, serif; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 34px; margin: 0 0 8px; }
    p { color: var(--muted); margin: 0 0 20px; }
    .controls, .cards, .charts { display: grid; gap: 16px; }
    .controls { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 16px; }
    .cards { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 16px; }
    .charts { grid-template-columns: 1.5fr 1fr; }
    .panel { background: rgba(19,39,43,0.9); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }
    .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
    .value { font-size: 28px; margin-top: 6px; }
    select { width: 100%; padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: #0f2024; color: var(--ink); }
    svg { width: 100%; height: auto; display: block; }
    .legend { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; color: var(--muted); font-size: 13px; }
    .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 999px; margin-right: 6px; }
    .good::before { background: var(--good); }
    .okay::before { background: var(--okay); }
    .bad::before { background: var(--bad); }
    .missing::before { background: var(--missing); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    td, th { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.08); text-align: left; }
    @media (max-width: 900px) { .charts { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Posture Trends</h1>
    <p>Always-on posture history from the Jetson runtime.</p>
    <div class="controls">
      <div class="panel">
        <div class="label">Window</div>
        <select id="hours">
          <option value="6">Last 6 hours</option>
          <option value="24" selected>Last 24 hours</option>
          <option value="72">Last 3 days</option>
          <option value="168">Last 7 days</option>
        </select>
      </div>
      <div class="panel">
        <div class="label">Bucket Size</div>
        <select id="bucket">
          <option value="1">1 minute</option>
          <option value="5" selected>5 minutes</option>
          <option value="15">15 minutes</option>
          <option value="60">60 minutes</option>
        </select>
      </div>
    </div>
    <div class="cards" id="cards"></div>
    <div class="charts">
      <div class="panel">
        <div class="label">Posture Score Over Time</div>
        <svg id="scoreChart" viewBox="0 0 860 300" preserveAspectRatio="none"></svg>
        <div class="legend">
          <span class="good">good = 1</span>
          <span class="okay">okay = 0</span>
          <span class="bad">bad = -1</span>
        </div>
      </div>
      <div class="panel">
        <div class="label">Posture Mix By Time Bucket</div>
        <svg id="mixChart" viewBox="0 0 500 300" preserveAspectRatio="none"></svg>
        <div class="legend">
          <span class="good">good</span>
          <span class="okay">okay</span>
          <span class="bad">bad</span>
          <span class="missing">not found</span>
        </div>
      </div>
    </div>
    <div class="charts" style="margin-top:16px;">
      <div class="panel">
        <div class="label">Daily Summary</div>
        <table>
          <thead><tr><th>Day</th><th>Good %</th><th>Avg Score</th><th>Longest Good Streak</th></tr></thead>
          <tbody id="days"></tbody>
        </table>
      </div>
      <div class="panel">
        <div class="label">Streaks</div>
        <table>
          <tbody id="streaks"></tbody>
        </table>
      </div>
    </div>
    <div class="panel" style="margin-top:16px;">
      <div class="label">Recent Status Changes</div>
      <table>
        <thead><tr><th>Time</th><th>Status</th><th>Confidence</th></tr></thead>
        <tbody id="events"></tbody>
      </table>
    </div>
  </div>
  <script>
    const scoreSvg = document.getElementById("scoreChart");
    const mixSvg = document.getElementById("mixChart");
    const cards = document.getElementById("cards");
    const eventsBody = document.getElementById("events");
    const daysBody = document.getElementById("days");
    const streaksBody = document.getElementById("streaks");
    const hoursEl = document.getElementById("hours");
    const bucketEl = document.getElementById("bucket");

    function card(label, value) {
      return `<div class="panel"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    }

    function formatTime(ts) {
      return new Date(ts * 1000).toLocaleString();
    }

    function renderCards(summary) {
      cards.innerHTML =
        card("Latest Status", summary.latest_status || "n/a") +
        card("Average Score", summary.avg_score === null ? "n/a" : summary.avg_score.toFixed(2)) +
        card("Samples", summary.sample_count) +
        card("Sessions", summary.session_count);
    }

    function renderScoreChart(series) {
      const w = 860, h = 300, pad = 30;
      const points = series.filter(row => row.avg_score !== null);
      if (!points.length) {
        scoreSvg.innerHTML = "";
        return;
      }
      const minTs = points[0].bucket_ts;
      const maxTs = points[points.length - 1].bucket_ts || minTs + 1;
      const lines = [];
      for (let idx = 0; idx < 3; idx += 1) {
        const value = 1 - idx;
        const y = pad + ((1 - value) / 2) * (h - pad * 2);
        lines.push(`<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="rgba(255,255,255,0.08)" />`);
      }
      const coords = points.map(point => {
        const x = pad + ((point.bucket_ts - minTs) / Math.max(maxTs - minTs, 1)) * (w - pad * 2);
        const y = pad + ((1 - point.avg_score) / 2) * (h - pad * 2);
        return `${x},${y}`;
      });
      scoreSvg.innerHTML = `
        <rect x="0" y="0" width="${w}" height="${h}" fill="transparent" />
        ${lines.join("")}
        <polyline fill="none" stroke="#f3f5ef" stroke-width="3" points="${coords.join(" ")}" />
      `;
    }

    function renderMixChart(series) {
      const w = 500, h = 300, pad = 18;
      if (!series.length) {
        mixSvg.innerHTML = "";
        return;
      }
      const barWidth = Math.max(4, (w - pad * 2) / series.length);
      const colors = {good: "#79c36a", okay: "#f0c35b", bad: "#e16b5c", not_found: "#60757d"};
      const bars = [];
      series.forEach((row, idx) => {
        const total = Math.max(row.good_count + row.okay_count + row.bad_count + row.not_found_count, 1);
        let y = h - pad;
        [["good_count", "good"], ["okay_count", "okay"], ["bad_count", "bad"], ["not_found_count", "not_found"]].forEach(([field, colorKey]) => {
          const segmentH = ((row[field] || 0) / total) * (h - pad * 2);
          y -= segmentH;
          bars.push(`<rect x="${pad + idx * barWidth}" y="${y}" width="${barWidth - 1}" height="${segmentH}" fill="${colors[colorKey]}" />`);
        });
      });
      mixSvg.innerHTML = `<rect x="0" y="0" width="${w}" height="${h}" fill="transparent" />${bars.join("")}`;
    }

    function renderEvents(events) {
      eventsBody.innerHTML = events.map(event => `
        <tr>
          <td>${formatTime(event.ts_unix)}</td>
          <td>${event.oled_status_text}</td>
          <td>${event.posture_confidence === null ? "n/a" : event.posture_confidence.toFixed(2)}</td>
        </tr>
      `).join("");
    }

    function formatMinutes(value) {
      if (value === null || value === undefined) {
        return "n/a";
      }
      if (value < 60) {
        return `${value.toFixed(0)} min`;
      }
      return `${(value / 60).toFixed(1)} hr`;
    }

    function renderAnalytics(analytics) {
      daysBody.innerHTML = analytics.daily_rows.map(row => `
        <tr>
          <td>${row.day}</td>
          <td>${(row.good_ratio * 100).toFixed(0)}%</td>
          <td>${row.avg_score === null ? "n/a" : row.avg_score.toFixed(2)}</td>
          <td>${formatMinutes(row.longest_good_streak_min)}</td>
        </tr>
      `).join("");
      streaksBody.innerHTML = [
        ["Current good streak", formatMinutes(analytics.current_good_streak_min)],
        ["Longest good streak", formatMinutes(analytics.longest_good_streak_min)],
        ["Current non-bad streak", formatMinutes(analytics.current_non_bad_streak_min)],
        ["Longest non-bad streak", formatMinutes(analytics.longest_non_bad_streak_min)],
      ].map(([label, value]) => `<tr><th>${label}</th><td>${value}</td></tr>`).join("");
    }

    async function refresh() {
      const hours = hoursEl.value;
      const bucket = bucketEl.value;
      const [summaryResp, seriesResp, eventsResp, analyticsResp] = await Promise.all([
        fetch(`/api/summary?hours=${hours}`),
        fetch(`/api/series?hours=${hours}&bucket_minutes=${bucket}`),
        fetch(`/api/events?hours=${hours}`),
        fetch(`/api/analytics?hours=${hours}`),
      ]);
      const summary = await summaryResp.json();
      const series = await seriesResp.json();
      const events = await eventsResp.json();
      const analytics = await analyticsResp.json();
      renderCards(summary);
      renderScoreChart(series.rows);
      renderMixChart(series.rows);
      renderEvents(events.rows);
      renderAnalytics(analytics);
    }

    hoursEl.addEventListener("change", refresh);
    bucketEl.addEventListener("change", refresh);
    refresh();
    setInterval(refresh, 30000);
  </script>
</body>
</html>
"""


def query_summary(conn: sqlite3.Connection, hours: int) -> Dict[str, object]:
    since = time.time() - hours * 3600
    summary_row = conn.execute(
        """
        SELECT
          COUNT(*) AS sample_count,
          AVG(posture_value) AS avg_score,
          SUM(CASE WHEN status_label = 'good' THEN 1 ELSE 0 END) AS good_count,
          SUM(CASE WHEN status_label = 'okay' THEN 1 ELSE 0 END) AS okay_count,
          SUM(CASE WHEN status_label = 'bad' THEN 1 ELSE 0 END) AS bad_count,
          SUM(CASE WHEN status_label = 'not_found' THEN 1 ELSE 0 END) AS not_found_count
        FROM posture_samples
        WHERE ts_unix >= ?
        """,
        (since,),
    ).fetchone()
    latest_row = conn.execute(
        """
        SELECT oled_status_text
        FROM posture_samples
        ORDER BY ts_unix DESC
        LIMIT 1
        """
    ).fetchone()
    session_count = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE started_at >= ?",
        (since,),
    ).fetchone()[0]
    return {
        "sample_count": int(summary_row["sample_count"] or 0),
        "avg_score": summary_row["avg_score"],
        "good_count": int(summary_row["good_count"] or 0),
        "okay_count": int(summary_row["okay_count"] or 0),
        "bad_count": int(summary_row["bad_count"] or 0),
        "not_found_count": int(summary_row["not_found_count"] or 0),
        "session_count": int(session_count),
        "latest_status": latest_row["oled_status_text"] if latest_row else None,
    }


def query_series(conn: sqlite3.Connection, hours: int, bucket_minutes: int) -> Dict[str, List[Dict[str, object]]]:
    since = time.time() - hours * 3600
    bucket_seconds = max(bucket_minutes, 1) * 60
    rows = conn.execute(
        """
        WITH bucketed AS (
          SELECT
            CAST(ts_unix / ? AS INTEGER) * ? AS bucket_ts,
            AVG(posture_value) AS avg_score,
            SUM(CASE WHEN status_label = 'good' THEN 1 ELSE 0 END) AS good_count,
            SUM(CASE WHEN status_label = 'okay' THEN 1 ELSE 0 END) AS okay_count,
            SUM(CASE WHEN status_label = 'bad' THEN 1 ELSE 0 END) AS bad_count,
            SUM(CASE WHEN status_label = 'not_found' THEN 1 ELSE 0 END) AS not_found_count
          FROM posture_samples
          WHERE ts_unix >= ?
          GROUP BY bucket_ts
          ORDER BY bucket_ts
        )
        SELECT * FROM bucketed
        """,
        (bucket_seconds, bucket_seconds, since),
    ).fetchall()
    return {
        "rows": [
            {
                "bucket_ts": row["bucket_ts"],
                "avg_score": row["avg_score"],
                "good_count": row["good_count"],
                "okay_count": row["okay_count"],
                "bad_count": row["bad_count"],
                "not_found_count": row["not_found_count"],
            }
            for row in rows
        ]
    }


def query_events(conn: sqlite3.Connection, hours: int) -> Dict[str, List[Dict[str, object]]]:
    since = time.time() - hours * 3600
    rows = conn.execute(
        """
        SELECT ts_unix, oled_status_text, posture_confidence
        FROM posture_events
        WHERE ts_unix >= ?
        ORDER BY ts_unix DESC
        LIMIT 50
        """,
        (since,),
    ).fetchall()
    return {
        "rows": [
            {
                "ts_unix": row["ts_unix"],
                "oled_status_text": row["oled_status_text"],
                "posture_confidence": row["posture_confidence"],
            }
            for row in rows
        ]
    }


def _fetch_samples(conn: sqlite3.Connection, since: float) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ts_unix, status_label, posture_value
        FROM posture_samples
        WHERE ts_unix >= ?
        ORDER BY ts_unix
        """,
        (since,),
    ).fetchall()


def _segment_minutes(start_ts: float, end_ts: float) -> float:
    return max(end_ts - start_ts, 0.0) / 60.0


def _status_matches(status_label: str, allowed: set[str]) -> bool:
    return status_label in allowed


def _compute_streaks(samples: List[sqlite3.Row], now_ts: float, allowed: set[str]) -> Dict[str, Optional[float]]:
    longest = 0.0
    current = 0.0
    streak_start_ts: Optional[float] = None
    previous_ts: Optional[float] = None

    for row in samples:
        ts_unix = float(row["ts_unix"])
        status_label = str(row["status_label"])
        if _status_matches(status_label, allowed):
            if streak_start_ts is None:
                streak_start_ts = ts_unix
            previous_ts = ts_unix
        else:
            if streak_start_ts is not None and previous_ts is not None:
                longest = max(longest, _segment_minutes(streak_start_ts, previous_ts))
            streak_start_ts = None
            previous_ts = None

    if streak_start_ts is not None and previous_ts is not None:
        effective_end_ts = now_ts if (now_ts - previous_ts) <= ACTIVE_SAMPLE_WINDOW_S else previous_ts
        current = _segment_minutes(streak_start_ts, effective_end_ts)
        longest = max(longest, current)

    return {
        "current_min": current if samples else None,
        "longest_min": longest if samples else None,
    }


def query_analytics(conn: sqlite3.Connection, hours: int) -> Dict[str, object]:
    now_ts = time.time()
    since = now_ts - hours * 3600
    samples = _fetch_samples(conn, since)

    day_buckets: Dict[str, Dict[str, object]] = {}
    for row in samples:
        ts_unix = float(row["ts_unix"])
        day = dt.datetime.fromtimestamp(ts_unix).strftime("%Y-%m-%d")
        bucket = day_buckets.setdefault(
            day,
            {
                "day": day,
                "count": 0,
                "good_count": 0,
                "score_sum": 0.0,
                "score_count": 0,
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        if row["status_label"] == "good":
            bucket["good_count"] = int(bucket["good_count"]) + 1
        if row["posture_value"] is not None:
            bucket["score_sum"] = float(bucket["score_sum"]) + float(row["posture_value"])
            bucket["score_count"] = int(bucket["score_count"]) + 1

    daily_rows = []
    for day, bucket in sorted(day_buckets.items(), reverse=True)[:14]:
        day_start = dt.datetime.strptime(day, "%Y-%m-%d").timestamp()
        day_end = day_start + 86400
        day_samples = [row for row in samples if day_start <= float(row["ts_unix"]) < day_end]
        streak = _compute_streaks(day_samples, min(day_end, now_ts), {"good"})
        good_ratio = (bucket["good_count"] / bucket["count"]) if bucket["count"] else 0.0
        avg_score = (
            float(bucket["score_sum"]) / int(bucket["score_count"])
            if bucket["score_count"] else None
        )
        daily_rows.append(
            {
                "day": day,
                "good_ratio": good_ratio,
                "avg_score": avg_score,
                "longest_good_streak_min": streak["longest_min"],
            }
        )

    good_streak = _compute_streaks(samples, now_ts, {"good"})
    non_bad_streak = _compute_streaks(samples, now_ts, {"good", "okay"})
    return {
        "current_good_streak_min": good_streak["current_min"],
        "longest_good_streak_min": good_streak["longest_min"],
        "current_non_bad_streak_min": non_bad_streak["current_min"],
        "longest_non_bad_streak_min": non_bad_streak["longest_min"],
        "daily_rows": daily_rows,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = ""

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _send_json(self, payload: Dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        hours = int(params.get("hours", ["24"])[0])
        conn = self._open_db()
        try:
            if parsed.path == "/":
                body = HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/summary":
                self._send_json(query_summary(conn, hours))
                return
            if parsed.path == "/api/series":
                bucket_minutes = int(params.get("bucket_minutes", ["5"])[0])
                self._send_json(query_series(conn, hours, bucket_minutes))
                return
            if parsed.path == "/api/events":
                self._send_json(query_events(conn, hours))
                return
            if parsed.path == "/api/analytics":
                self._send_json(query_analytics(conn, hours))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
        finally:
            conn.close()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    DashboardHandler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"[dashboard] serving db={args.db} on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
