"""Background ping monitoring for one diagnostic session.

Mirrors the logic in netwatch.sh (ping router, modem, and two public DNS
servers once a second; track up/down transitions as "outages") but runs as
Python threads so a Flask app can start/stop it and stream events live
instead of printing to a terminal.
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

import diagnosis

DEFAULT_HOSTS = {
    "cloudflare": "1.1.1.1",
    "google": "8.8.8.8",
}
PING_INTERVAL_SEC = 1.0
PING_TIMEOUT_MS = 1000
CONNECTION_CHECK_INTERVAL_SEC = 10.0


def _default_route_info():
    try:
        out = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    info = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("gateway:"):
            info["gateway"] = line.split(":", 1)[1].strip()
        elif line.startswith("interface:"):
            info["interface"] = line.split(":", 1)[1].strip()
    return info


def detect_gateway():
    return _default_route_info().get("gateway")


def _hardware_port_map():
    """Map network interface names (en0, en4, ...) to macOS hardware port
    names (Wi-Fi, Ethernet Adapter, Thunderbolt Ethernet, ...)."""
    try:
        out = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    mapping = {}
    current_port = None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("Hardware Port:"):
            current_port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and current_port:
            mapping[line.split(":", 1)[1].strip()] = current_port
    return mapping


def detect_connection_type():
    """'wifi', 'ethernet', 'offline', or 'unknown', based on whichever
    hardware port owns the interface currently holding the default route.
    'offline' means there's no default route at all -- not the same as
    'unknown', which means there IS a route but its hardware port couldn't
    be confidently classified (e.g. an unusual adapter). macOS-only (uses
    route(8) and networksetup(8)); always 'unknown' elsewhere."""
    interface = _default_route_info().get("interface")
    if not interface:
        return "offline"
    port_name = _hardware_port_map().get(interface, "").lower()
    if "wi-fi" in port_name or "airport" in port_name:
        return "wifi"
    if "ethernet" in port_name or "lan" in port_name:
        return "ethernet"
    return "unknown"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ping_once(host, timeout_ms=PING_TIMEOUT_MS):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_ms), host],
            capture_output=True, text=True, timeout=(timeout_ms / 1000) + 1,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, None
    if result.returncode != 0:
        return False, None
    match = re.search(r"time=([\d.]+)", result.stdout)
    return True, (float(match.group(1)) if match else None)


def summarize(data):
    """Per-target outage counts/downtime for a session dict."""
    per_target = {}
    for outage in data.get("outages", []):
        t = outage["target"]
        bucket = per_target.setdefault(t, {"count": 0, "downtime_sec": 0.0})
        bucket["count"] += 1
        bucket["downtime_sec"] += outage.get("duration_sec") or 0

    connection_history = data.get("connection_history", [])

    diag = diagnosis.diagnose_or_default(data)
    brief_diagnosis = (
        {"category": diag["category"], "label": diag["label"], "guide_anchor": diag["guide_anchor"]}
        if diag is not None
        else None
    )

    return {
        "id": data["id"],
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "running": data.get("ended_at") is None,
        "per_target": per_target,
        "marked_count": len(data.get("marked_disruptions", [])),
        "total_outages": sum(v["count"] for v in per_target.values()),
        "connection_type": connection_history[-1]["type"] if connection_history else "unknown",
        "connection_changed": len(connection_history) > 1,
        "diagnosis": brief_diagnosis,
    }


class SessionMonitor:
    """Runs one ping thread per target for the life of a session."""

    def __init__(self, sessions_dir, on_event=None, modem_ip=None):
        self.sessions_dir = sessions_dir
        self.on_event = on_event or (lambda event: None)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.targets = {
            "router": detect_gateway(),
            "modem": modem_ip or "192.168.100.1",
            **DEFAULT_HOSTS,
        }
        self.started_at = now_iso()
        self.ended_at = None

        self.lock = threading.Lock()
        self.live_status = {label: "unknown" for label in self.targets}
        self.outages = []       # completed outage windows
        self._open_outages = {}  # label -> in-progress outage dict
        self.marked = []
        # Timeline of connection type over the session's life -- usually
        # one entry, but records a new one (with timestamp) if the machine
        # switches between Ethernet and WiFi mid-session.
        self.connection_history = [{"type": detect_connection_type(), "since": self.started_at}]
        self.recent_events = []  # rolling log so a reloaded page can catch up

        self._stop_event = threading.Event()
        self._threads = []

    # -- lifecycle ---------------------------------------------------

    def start(self):
        for label, host in self.targets.items():
            if not host:
                continue
            thread = threading.Thread(target=self._loop, args=(label, host), daemon=True)
            self._threads.append(thread)
            thread.start()

        watcher = threading.Thread(target=self._connection_watch_loop, daemon=True)
        self._threads.append(watcher)
        watcher.start()

    def stop(self):
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=3)

        with self.lock:
            self.ended_at = now_iso()
            for outage in self._open_outages.values():
                outage["end"] = self.ended_at
                outage["duration_sec"] = round(time.time() - outage.pop("_start_epoch"), 1)
                self.outages.append(outage)
            self._open_outages = {}

        data = self.to_dict()
        data["diagnosis"] = diagnosis.diagnose(data)
        self._save(data)
        return summarize(data)

    # -- reporting -----------------------------------------------------

    def status(self):
        with self.lock:
            return {
                "running": True,
                "session_id": self.session_id,
                "started_at": self.started_at,
                "targets": dict(self.targets),
                "connection_type": self.connection_history[-1]["type"],
                "connection_history": [dict(c) for c in self.connection_history],
                "live_status": dict(self.live_status),
                "recent_events": list(self.recent_events[-50:]),
                "marked": list(self.marked),
            }

    def to_dict(self):
        with self.lock:
            return {
                "id": self.session_id,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "targets": dict(self.targets),
                "connection_history": [dict(c) for c in self.connection_history],
                "outages": [dict(o) for o in self.outages],
                "marked_disruptions": [dict(m) for m in self.marked],
            }

    # -- mutation --------------------------------------------------------

    def mark_disruption(self, note=""):
        entry = {"id": uuid.uuid4().hex[:8], "timestamp": now_iso(), "note": note}
        with self.lock:
            self.marked.append(entry)
        self._save()
        self._emit({"type": "marked_created", "entry": entry})
        return entry

    def update_note(self, mark_id, note):
        with self.lock:
            for entry in self.marked:
                if entry["id"] == mark_id:
                    entry["note"] = note
                    updated = dict(entry)
                    break
            else:
                return None
        self._save()
        return updated

    # -- internals ---------------------------------------------------------

    def _loop(self, label, host):
        while not self._stop_event.is_set():
            up, _latency = ping_once(host)
            ts = now_iso()

            with self.lock:
                prev = self.live_status[label]
                self.live_status[label] = "up" if up else "down"

            if prev == "unknown" and up:
                # The common case: the target was already up when monitoring
                # started. Nothing to close out, but the badge still needs
                # to hear about it -- it starts at "unknown", not "down", so
                # neither branch below would otherwise ever fire for it.
                self._emit({"type": "initial_status", "target": label, "host": host, "status": "up"})
            elif up and prev == "down":
                with self.lock:
                    outage = self._open_outages.pop(label, None)
                if outage is not None:
                    outage["end"] = ts
                    outage["duration_sec"] = round(time.time() - outage.pop("_start_epoch"), 1)
                    with self.lock:
                        self.outages.append(outage)
                    self._save()
                self._emit({"type": "recovered", "target": label, "host": host})
            elif not up and prev != "down":
                outage = {"target": label, "host": host, "start": ts, "_start_epoch": time.time()}
                with self.lock:
                    self._open_outages[label] = outage
                self._emit({"type": "down", "target": label, "host": host})

            self._stop_event.wait(PING_INTERVAL_SEC)

    def _connection_watch_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(CONNECTION_CHECK_INTERVAL_SEC)
            if self._stop_event.is_set():
                break

            current = detect_connection_type()
            with self.lock:
                changed = current != self.connection_history[-1]["type"]
                if changed:
                    entry = {"type": current, "since": now_iso()}
                    self.connection_history.append(entry)
            if changed:
                self._save()
                self._emit({"type": "connection_changed", "connection_type": current})

    def _emit(self, event):
        event = {"timestamp": now_iso(), **event}
        with self.lock:
            self.recent_events.append(event)
            self.recent_events = self.recent_events[-200:]
        self.on_event(event)

    def _save(self, data=None):
        data = data or self.to_dict()
        path = os.path.join(self.sessions_dir, f"{self.session_id}.json")
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
