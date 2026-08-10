"""Reading, writing, and summarizing past sessions on disk.

Each session is one JSON file at data/sessions/<session_id>.json. There's no
database — at the scale of "a handful of monitoring sessions for one house",
a directory of JSON files is simpler to read, back up, and hand to a
non-technical person than standing up SQLite would be.
"""
import glob
import io
import json
import os
import zipfile

from monitor import summarize


def _session_path(sessions_dir, session_id):
    # session_id comes from the URL path; keep it to the timestamp-derived
    # format we generate so it can't be used to escape sessions_dir.
    safe_id = os.path.basename(session_id)
    return os.path.join(sessions_dir, f"{safe_id}.json")


def load_session(sessions_dir, session_id):
    path = _session_path(sessions_dir, session_id)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _write_session(sessions_dir, session_id, data):
    path = _session_path(sessions_dir, session_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def list_sessions(sessions_dir):
    sessions = []
    for path in sorted(glob.glob(os.path.join(sessions_dir, "*.json")), reverse=True):
        with open(path) as f:
            data = json.load(f)
        sessions.append(summarize(data))
    return sessions


def update_mark_note(sessions_dir, session_id, mark_id, note):
    data = load_session(sessions_dir, session_id)
    if data is None:
        return None
    for entry in data.get("marked_disruptions", []):
        if entry["id"] == mark_id:
            entry["note"] = note
            _write_session(sessions_dir, session_id, data)
            return entry
    return None


def recover_incomplete_sessions(sessions_dir):
    """If the server was killed mid-session, close the file out on next boot
    so it shows up in history instead of silently vanishing."""
    for path in glob.glob(os.path.join(sessions_dir, "*.json")):
        with open(path) as f:
            data = json.load(f)
        if data.get("ended_at") is None:
            data["ended_at"] = data.get("started_at")
            data["note_incomplete"] = (
                "The app was closed while this session was still running, "
                "so the end time above is not accurate."
            )
            tmp_path = path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)


def build_download_bundle(data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.txt", build_summary_text(data))
        zf.writestr("events.csv", build_events_csv(data))
        zf.writestr("raw.json", json.dumps(data, indent=2))
    buf.seek(0)
    return buf


def build_summary_text(data):
    lines = [
        "Internet Diagnostic Session Summary",
        f"Session ID: {data['id']}",
        f"Started: {data.get('started_at')}",
        f"Ended:   {data.get('ended_at')}",
        "",
        "Targets monitored:",
    ]
    for label, host in data.get("targets", {}).items():
        lines.append(f"  - {label}: {host}")
    lines.append("")

    connection_history = data.get("connection_history", [])
    if connection_history:
        lines.append("Network connection (this machine, not the whole household):")
        for entry in connection_history:
            lines.append(f"  - {entry['type']} from {entry['since']}")
        lines.append("")

    summary = summarize(data)
    lines.append("Outages by target:")
    if not summary["per_target"]:
        lines.append("  None detected.")
    for label, stats in summary["per_target"].items():
        lines.append(f"  - {label}: {stats['count']} outage(s), {stats['downtime_sec']:.1f}s total downtime")
    lines.append("")

    lines.append("Outage windows (when connectivity to a target was lost):")
    if not data.get("outages"):
        lines.append("  None detected.")
    for outage in data.get("outages", []):
        lines.append(
            f"  [{outage['target']}] {outage['start']} -> {outage.get('end', '?')} "
            f"({outage.get('duration_sec', '?')}s) host={outage.get('host')}"
        )
    lines.append("")

    lines.append("User-reported disruptions (marked during a call):")
    if not data.get("marked_disruptions"):
        lines.append("  None reported.")
    for entry in data.get("marked_disruptions", []):
        note = entry.get("note") or "(no note)"
        lines.append(f"  [{entry['timestamp']}] {note}")

    return "\n".join(lines) + "\n"


def build_events_csv(data):
    rows = ["type,target,start_or_timestamp,end,duration_sec,note"]
    for outage in data.get("outages", []):
        rows.append(
            f"outage,{outage['target']},{outage['start']},{outage.get('end', '')},"
            f"{outage.get('duration_sec', '')},"
        )
    for entry in data.get("marked_disruptions", []):
        note = (entry.get("note") or "").replace(",", ";").replace("\n", " ")
        rows.append(f"marked,,{entry['timestamp']},,,{note}")
    for entry in data.get("connection_history", []):
        rows.append(f"connection,{entry['type']},{entry['since']},,,")
    return "\n".join(rows) + "\n"
