"""Push notifications via ntfy.sh for Smart Garden alerts.

Sends alerts when the system detects problems:
- ESP32 offline for >15 minutes
- Crash-loop (boot_count jumps >5 in 30 min)
- Safe mode activated
- Sensor flatlined for >48 hours
- Memory critically low (<15%)

Uses ntfy.sh — free, no account needed, push to any phone.
Subscribe to topic on phone: https://ntfy.sh/smart-garden-james
"""

import logging
import time
import requests
import database as db

log = logging.getLogger("smart-garden")

NTFY_TOPIC = "smart-garden-james"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# Cooldown: don't repeat the same alert within this many seconds
ALERT_COOLDOWN_SEC = 1800  # 30 minutes


class AlertMonitor:
    def __init__(self, config: dict, engine):
        self.config = config
        self.engine = engine
        self._last_alert = {}  # alert_key -> timestamp
        self._last_boot_count = None
        self._offline_since = None
        # Snapshot of last seen counters — used to detect deltas, not absolutes.
        # First poll after restart populates these without alerting.
        self._snap = {
            "bootCount": None,
            "wifiReconnects": None,
            "crashCount": None,
            "freeHeap": None,
            "freeHeap_high": None,  # rolling 24h max for leak detection
        }
        # Consecutive-sample counter for chip temp. ESP32 internal temp sensor is
        # uncalibrated and noisy — single-sample spikes to 100C+ are common while
        # the real die temp is stable. Require N consecutive over-threshold reads
        # before paging. See mistake-ledger M6 + smart-garden journey 2026-04-22.
        self._chip_temp_over = 0

    def _should_alert(self, key: str) -> bool:
        now = time.time()
        last = self._last_alert.get(key, 0)
        if now - last < ALERT_COOLDOWN_SEC:
            return False
        self._last_alert[key] = now
        return True

    def _send(self, title: str, message: str, priority: str = "high",
              tags: str = "warning"):
        # ntfy.sh sends Title via HTTP header. The `requests` library encodes
        # headers as latin-1, which fails on emoji (✅ 🔴 ⚠️). The `tags` field
        # already renders as an emoji prefix on the phone, so emoji in the
        # title is redundant — strip them here defensively.
        safe_title = title.encode("ascii", errors="ignore").decode("ascii").strip()
        if not safe_title:
            safe_title = "Smart Garden Alert"
        try:
            requests.post(NTFY_URL, data=message.encode("utf-8"), headers={
                "Title": safe_title,
                "Priority": priority,
                "Tags": tags,
            }, timeout=10)
            log.info("Alert sent: %s — %s", safe_title, message)
        except Exception as e:
            log.error("Failed to send alert: %s", e)

    def check(self):
        """Run all alert checks. Called every poll cycle by the scheduler."""
        try:
            status = self.engine.get_esp32_status()
            self._check_offline()
            self._check_crash_loop()
            self._check_safe_mode(status)
            self._check_memory(status)
            self._check_sensor_faults()
            self._check_counter_deltas(status)
            self._check_chip_temp(status)
        except Exception as e:
            log.error("Alert check failed: %s", e)

    def _check_offline(self):
        conn = db.get_last_connectivity()
        if not conn:
            return

        if not conn.get("success", True):
            if self._offline_since is None:
                self._offline_since = time.time()
            elapsed_min = (time.time() - self._offline_since) / 60
            if elapsed_min >= 15 and self._should_alert("offline"):
                self._send(
                    "🔴 ESP32 Offline",
                    f"ESP32 has been unreachable for {int(elapsed_min)} minutes.\n"
                    f"Last error: {conn.get('error_message', 'unknown')}",
                    priority="urgent", tags="rotating_light",
                )
        else:
            if self._offline_since is not None:
                # Back online — send recovery notice
                down_min = int((time.time() - self._offline_since) / 60)
                if down_min >= 15 and self._should_alert("recovery"):
                    self._send(
                        "✅ ESP32 Back Online",
                        f"System recovered after {down_min} minutes offline.",
                        priority="default", tags="white_check_mark",
                    )
                self._offline_since = None

    def _check_crash_loop(self):
        history = db.get_connectivity_history(hours=1)
        if len(history) < 2:
            return
        first_boot = history[0].get("boot_count")
        last_boot = history[-1].get("boot_count")
        if first_boot is not None and last_boot is not None:
            delta = last_boot - first_boot
            if delta > 5 and self._should_alert("crash_loop"):
                self._send(
                    "🔴 Crash-Loop Detected",
                    f"{delta} reboots in the last hour.\n"
                    f"Boot count: {first_boot} → {last_boot}",
                    priority="urgent", tags="rotating_light",
                )

    def _check_safe_mode(self, status):
        if not status:
            return
        sys = status.get("system", {})
        if sys.get("safeMode") and self._should_alert("safe_mode"):
            self._send(
                "⚠️ Safe Mode Active",
                f"ESP32 entered safe mode after {sys.get('crashCount', '?')} crashes.\n"
                "Deep sleep protection engaged. Manual reset may be needed.",
                priority="high", tags="warning",
            )

    def _check_memory(self, status):
        if not status:
            return
        heap_pct = status.get("system", {}).get("heapPct")
        if heap_pct is not None and heap_pct < 15 and self._should_alert("low_memory"):
            self._send(
                "⚠️ Memory Critical",
                f"ESP32 free heap at {heap_pct}% ({status['system'].get('freeHeap', '?')} bytes).\n"
                "Risk of crash. Consider restarting.",
                priority="high", tags="warning",
            )

    def _check_sensor_faults(self):
        for zone in self.config.get("zones", []):
            if not zone.get("installed", False):
                continue
            sensor_id = zone["soil_sensor"]
            anomaly = db.get_sensor_flatline(sensor_id, hours=48)
            if anomaly.get("railed") and self._should_alert(f"railed_{sensor_id}"):
                self._send(
                    f"⚠️ Sensor Fault: {zone['name']}",
                    f"Sensor {sensor_id} railed at {anomaly['min_pct']}% for 48+ hours.\n"
                    f"Raw ADC range: {anomaly['min_raw']}–{anomaly['max_raw']}.\n"
                    "Likely disconnected or broken.",
                    priority="default", tags="warning",
                )
            elif anomaly.get("flatline") and self._should_alert(f"flat_{sensor_id}"):
                self._send(
                    f"⚠️ Sensor Flatline: {zone['name']}",
                    f"Sensor {sensor_id} reading constant {anomaly['min_pct']}% for 48+ hours.\n"
                    "May be stuck or in standing water.",
                    priority="default", tags="warning",
                )

    def _check_counter_deltas(self, status):
        """Alert when persistent counters increment unexpectedly.

        bootCount, wifiReconnects, crashCount are all NVS-persistent. Steady
        state on wall power = zero change between polls. Any delta is news.
        """
        if not status:
            return
        sys_block = status.get("system", {}) or {}
        health = status.get("health", {}) or {}

        for key, source, label, tag, prio in [
            ("bootCount", sys_block, "Unexpected reboot", "warning", "high"),
            ("wifiReconnects", sys_block, "WiFi reconnect", "satellite", "default"),
            ("crashCount", health, "Crash counter incremented", "rotating_light", "high"),
        ]:
            cur = source.get(key)
            if cur is None:
                continue
            prev = self._snap.get(key)
            if prev is None:
                # First poll after restart — just snapshot, don't alert
                self._snap[key] = cur
                continue
            if cur > prev:
                delta = cur - prev
                if self._should_alert(f"delta_{key}"):
                    self._send(
                        f"{label} (+{delta})",
                        f"{key}: {prev} -> {cur} (delta {delta}).",
                        priority=prio, tags=tag,
                    )
            self._snap[key] = cur

    def _check_chip_temp(self, status):
        if not status:
            return
        temp = (status.get("system", {}) or {}).get("chipTempC")
        if temp is None:
            return
        # Hysteresis: require 3 consecutive reads above 85C before paging.
        # Single-sample spikes are sensor noise (see M6).
        if temp > 85:
            self._chip_temp_over += 1
        else:
            self._chip_temp_over = 0
        if self._chip_temp_over >= 3 and self._should_alert("chip_temp"):
            self._send(
                f"ESP32 chip temp {temp:.1f}C",
                f"chipTempC = {temp:.1f}C for 3 consecutive reads (threshold 85C). "
                "Check enclosure ventilation or sun exposure.",
                priority="high", tags="thermometer",
            )

    def daily_digest(self):
        """Fired once a day at 8 AM by the scheduler. One ntfy, summary of last 24h."""
        try:
            status = self.engine.get_esp32_status() or {}
            sys_block = status.get("system", {}) or {}
            health = status.get("health", {}) or {}
            history = db.get_connectivity_history(hours=24) or []
            boots_24h = 0
            if len(history) >= 2:
                bf = history[0].get("boot_count")
                bl = history[-1].get("boot_count")
                if bf is not None and bl is not None:
                    boots_24h = bl - bf
            online = sum(1 for h in history if h.get("success"))
            online_pct = (online / len(history) * 100) if history else 0

            lines = [
                f"uptime: {sys_block.get('uptimeSec', '?')}s",
                f"RSSI: {sys_block.get('wifiRSSI', '?')} dBm",
                f"reconnects: {sys_block.get('wifiReconnects', '?')}",
                f"crashes: {health.get('crashCount', '?')}",
                f"bootCount: {sys_block.get('bootCount', '?')} (+{boots_24h} in 24h)",
                f"chipTempC: {sys_block.get('chipTempC', '?')}",
                f"freeHeap: {sys_block.get('freeHeap', '?')}",
                f"24h dashboard online: {online_pct:.0f}%",
            ]
            self._send(
                "Daily health digest",
                "\n".join(lines),
                priority="low", tags="bar_chart",
            )
        except Exception as e:
            log.error("Daily digest failed: %s", e)

    def startup_ping(self):
        """One ntfy on server start to confirm the alert pipeline is alive."""
        try:
            self._send(
                "Smart-garden server started",
                "Alert pipeline confirmed working. Daily digest at 8 AM.",
                priority="low", tags="seedling",
            )
        except Exception as e:
            log.error("Startup ping failed: %s", e)
