#!/usr/bin/env python3
"""
Smart Garden Query API

A lightweight HTTP server that exposes the SQLite telemetry database
for querying. Runs on the Acer home server alongside the collector.

Endpoints:
    GET /                        — Dashboard (HTML)
    GET /api/latest              — Most recent sensor reading
    GET /api/readings?hours=24   — Sensor readings for last N hours
    GET /api/valves/summary      — Per-valve lifetime stats
    GET /api/valves/history?hours=24&valve=0  — Valve state history
    GET /api/events?hours=24     — System events
    GET /api/health              — System health summary
    GET /api/export/csv?hours=24 — CSV export of sensor readings

Usage:
    python3 query_api.py                   # Port 5150 (default)
    python3 query_api.py --port 5150       # Custom port
"""

import argparse
import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "smart-garden.db"))
DEFAULT_PORT = 5150


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def epoch_hours_ago(hours: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress default access logs

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_csv(self, csv_text, filename="export.csv"):
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", f"attachment; filename={filename}")
        self.end_headers()
        self.wfile.write(csv_text.encode())

    def _params(self):
        return parse_qs(urlparse(self.path).query)

    def _get_hours(self, default=24):
        params = self._params()
        try:
            return int(params.get("hours", [str(default)])[0])
        except ValueError:
            return default

    def do_GET(self):
        path = urlparse(self.path).path

        try:
            if path == "/":
                self._handle_dashboard()
            elif path == "/api/latest":
                self._handle_latest()
            elif path == "/api/readings":
                self._handle_readings()
            elif path == "/api/valves/summary":
                self._handle_valves_summary()
            elif path == "/api/valves/history":
                self._handle_valves_history()
            elif path == "/api/events":
                self._handle_events()
            elif path == "/api/health":
                self._handle_health()
            elif path == "/api/export/csv":
                self._handle_export_csv()
            else:
                self._send_json({"error": "Not found"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_latest(self):
        conn = get_db()
        row = conn.execute("SELECT * FROM sensor_readings ORDER BY epoch DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            self._send_json(dict(row))
        else:
            self._send_json({"error": "No data yet"}, 404)

    def _handle_readings(self):
        hours = self._get_hours()
        since = epoch_hours_ago(hours)
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM sensor_readings WHERE epoch >= ? ORDER BY epoch ASC",
            (since,)
        ).fetchall()
        conn.close()
        self._send_json({"hours": hours, "count": len(rows), "readings": rows_to_dicts(rows)})

    def _handle_valves_summary(self):
        conn = get_db()
        # Get latest snapshot for each valve
        rows = conn.execute("""
            SELECT valve_id, valve_name,
                   MAX(open_count) as total_opens,
                   MAX(close_count) as total_closes,
                   -- Current state from most recent record
                   (SELECT is_open FROM valve_events v2
                    WHERE v2.valve_id = v1.valve_id
                    ORDER BY epoch DESC LIMIT 1) as current_state
            FROM valve_events v1
            GROUP BY valve_id
            ORDER BY valve_id
        """).fetchall()
        conn.close()
        self._send_json({"valves": rows_to_dicts(rows)})

    def _handle_valves_history(self):
        hours = self._get_hours()
        since = epoch_hours_ago(hours)
        params = self._params()
        valve_filter = params.get("valve", [None])[0]

        conn = get_db()
        if valve_filter is not None:
            rows = conn.execute(
                "SELECT * FROM valve_events WHERE epoch >= ? AND valve_id = ? ORDER BY epoch ASC",
                (since, int(valve_filter))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM valve_events WHERE epoch >= ? ORDER BY epoch ASC",
                (since,)
            ).fetchall()
        conn.close()
        self._send_json({"hours": hours, "count": len(rows), "events": rows_to_dicts(rows)})

    def _handle_events(self):
        hours = self._get_hours()
        since = epoch_hours_ago(hours)
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM system_events WHERE epoch >= ? ORDER BY epoch DESC LIMIT 200",
            (since,)
        ).fetchall()
        conn.close()
        self._send_json({"hours": hours, "count": len(rows), "events": rows_to_dicts(rows)})

    def _handle_health(self):
        conn = get_db()

        # Latest reading
        latest = conn.execute("SELECT * FROM sensor_readings ORDER BY epoch DESC LIMIT 1").fetchone()

        # Readings in last 24h
        since_24h = epoch_hours_ago(24)
        stats = conn.execute("""
            SELECT
                COUNT(*) as readings_24h,
                AVG(temp_f) as avg_temp,
                MIN(temp_f) as min_temp,
                MAX(temp_f) as max_temp,
                AVG(humidity) as avg_humidity,
                AVG(wifi_rssi) as avg_rssi,
                MIN(wifi_rssi) as min_rssi,
                AVG(heap_pct) as avg_heap_pct,
                MIN(heap_pct) as min_heap_pct
            FROM sensor_readings WHERE epoch >= ?
        """, (since_24h,)).fetchone()

        # Total DB size
        total_readings = conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        total_events = conn.execute("SELECT COUNT(*) FROM system_events").fetchone()[0]

        # DB file size
        db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024) if os.path.exists(DB_PATH) else 0

        conn.close()

        health = {
            "latest": dict(latest) if latest else None,
            "stats_24h": dict(stats) if stats else None,
            "database": {
                "total_readings": total_readings,
                "total_events": total_events,
                "size_mb": round(db_size_mb, 2),
            }
        }
        self._send_json(health)

    def _handle_export_csv(self):
        hours = self._get_hours()
        since = epoch_hours_ago(hours)
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM sensor_readings WHERE epoch >= ? ORDER BY epoch ASC",
            (since,)
        ).fetchall()
        conn.close()

        if not rows:
            self._send_csv("No data\n", f"smart-garden-{hours}h.csv")
            return

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(tuple(row))

        self._send_csv(output.getvalue(), f"smart-garden-{hours}h.csv")

    def _handle_dashboard(self):
        html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Smart Garden — History</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }
        h1 { color: #4ecca3; margin-bottom: 8px; }
        h2 { color: #4ecca3; margin: 20px 0 10px; font-size: 18px; }
        .subtitle { color: #888; font-size: 13px; margin-bottom: 16px; }
        .card { background: #16213e; border-radius: 12px; padding: 16px; margin-bottom: 12px; }
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
        .stat { background: #0f3460; border-radius: 8px; padding: 12px; text-align: center; }
        .stat .value { font-size: 24px; font-weight: bold; color: #4ecca3; }
        .stat .label { font-size: 11px; color: #aaa; margin-top: 4px; }
        .stat .sub { font-size: 10px; color: #666; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; color: #4ecca3; padding: 8px; border-bottom: 1px solid #0f3460; }
        td { padding: 6px 8px; border-bottom: 1px solid #0f3460; }
        .actions { margin: 16px 0; }
        .actions a { color: #4ecca3; margin-right: 16px; text-decoration: none; font-size: 13px; }
        .actions a:hover { text-decoration: underline; }
        .rssi-good { color: #4ecca3; }
        .rssi-ok { color: #e2b93d; }
        .rssi-bad { color: #e74c3c; }
        #error { color: #e74c3c; text-align: center; padding: 20px; }
    </style>
</head>
<body>
    <h1>🌱 Smart Garden — History</h1>
    <p class="subtitle">Long-term telemetry from the Acer data collector</p>

    <div class="actions">
        <a href="/api/health">Health JSON</a>
        <a href="/api/readings?hours=24">Readings (24h)</a>
        <a href="/api/valves/summary">Valve Stats</a>
        <a href="/api/events?hours=24">Events</a>
        <a href="/api/export/csv?hours=24">Export CSV (24h)</a>
        <a href="/api/export/csv?hours=168">Export CSV (7d)</a>
    </div>

    <div id="content"><p style="color:#888">Loading...</p></div>

    <script>
    function rssiClass(r) { return r > -50 ? 'rssi-good' : r > -70 ? 'rssi-ok' : 'rssi-bad'; }
    function fmt(n, d) { return n != null ? Number(n).toFixed(d || 0) : '—'; }

    async function load() {
        try {
            const health = await (await fetch('/api/health')).json();
            const l = health.latest || {};
            const s = health.stats_24h || {};
            const db = health.database || {};

            let html = '<h2>Current</h2><div class="card"><div class="stat-grid">';
            html += `<div class="stat"><div class="value">${fmt(l.temp_f,1)}°F</div><div class="label">Temperature</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(l.humidity,0)}%</div><div class="label">Humidity</div></div>`;
            html += `<div class="stat"><div class="value ${rssiClass(l.wifi_rssi)}">${l.wifi_rssi||'—'} dBm</div><div class="label">WiFi</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(l.heap_pct)}%</div><div class="label">Free Heap</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(l.chip_temp_f,0)}°F</div><div class="label">Chip Temp</div></div>`;
            html += `<div class="stat"><div class="value">${l.boot_count||'—'}</div><div class="label">Boots</div></div>`;
            html += '</div></div>';

            html += '<h2>24-Hour Summary</h2><div class="card"><div class="stat-grid">';
            html += `<div class="stat"><div class="value">${s.readings_24h||0}</div><div class="label">Readings</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(s.avg_temp,1)}°F</div><div class="label">Avg Temp</div><div class="sub">${fmt(s.min_temp,0)}–${fmt(s.max_temp,0)}°F</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(s.avg_humidity,0)}%</div><div class="label">Avg Humidity</div></div>`;
            html += `<div class="stat"><div class="value ${rssiClass(s.avg_rssi)}">${fmt(s.avg_rssi,0)} dBm</div><div class="label">Avg RSSI</div><div class="sub">min ${s.min_rssi||'—'}</div></div>`;
            html += `<div class="stat"><div class="value">${fmt(s.avg_heap_pct)}%</div><div class="label">Avg Heap</div><div class="sub">min ${s.min_heap_pct||'—'}%</div></div>`;
            html += '</div></div>';

            html += '<h2>Database</h2><div class="card"><div class="stat-grid">';
            html += `<div class="stat"><div class="value">${db.total_readings||0}</div><div class="label">Total Readings</div></div>`;
            html += `<div class="stat"><div class="value">${db.total_events||0}</div><div class="label">Total Events</div></div>`;
            html += `<div class="stat"><div class="value">${db.size_mb||0} MB</div><div class="label">DB Size</div></div>`;
            html += '</div></div>';

            document.getElementById('content').innerHTML = html;
        } catch(e) {
            document.getElementById('content').innerHTML = `<div id="error">Failed to load: ${e.message}</div>`;
        }
    }
    load();
    setInterval(load, 30000);
    </script>
</body>
</html>"""
        self._send_html(html)


def main():
    parser = argparse.ArgumentParser(description="Smart Garden Query API")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    print(f"Smart Garden Query API starting on http://127.0.0.1:{args.port}")
    print(f"Database: {DB_PATH}")
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.server_close()


if __name__ == "__main__":
    main()
