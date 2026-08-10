"""Flask app: start/stop the monitor, stream live events, browse/download
past sessions.

Run with `python3 server.py` (see ../run.sh for a one-command launcher that
also handles the virtualenv). Serves on http://127.0.0.1:5055.
"""
import json
import os
import queue
import signal
import sys
import threading

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

import storage
from monitor import SessionMonitor, summarize

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(REPO_ROOT, "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
GUIDE_PATH = os.path.join(REPO_ROOT, "docs", "interpreting-results.md")
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# All state below is protected by this one lock. Traffic on a local,
# single-user tool is low enough that a single lock is simpler than
# per-field locking and there's no meaningful contention to optimize away.
state_lock = threading.Lock()
current_monitor = None          # SessionMonitor | None
subscribers = []                # list[queue.Queue] — one per open /api/stream connection

storage.recover_incomplete_sessions(SESSIONS_DIR)


def broadcast(event):
    with state_lock:
        subs = list(subscribers)
    for q in subs:
        q.put(event)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/guide")
def guide():
    # Single source of truth for "how do I read this data" — also linked
    # from README.md so the explanation isn't maintained in two places.
    with open(GUIDE_PATH) as f:
        content = f.read()
    return Response(content, mimetype="text/markdown")


@app.route("/api/status")
def status():
    with state_lock:
        if current_monitor is None:
            return jsonify({"running": False})
        return jsonify(current_monitor.status())


@app.route("/api/start", methods=["POST"])
def start():
    global current_monitor
    with state_lock:
        if current_monitor is not None:
            return jsonify({"error": "A session is already running."}), 409
        current_monitor = SessionMonitor(SESSIONS_DIR, on_event=broadcast)
        current_monitor.start()
        result = current_monitor.status()
    return jsonify(result)


@app.route("/api/stop", methods=["POST"])
def stop():
    global current_monitor
    with state_lock:
        if current_monitor is None:
            return jsonify({"error": "No session is running."}), 409
        monitor = current_monitor
        current_monitor = None
    summary = monitor.stop()
    broadcast({"type": "session_ended", "summary": summary})
    return jsonify(summary)


@app.route("/api/mark", methods=["POST"])
def mark():
    note = ""
    if request.is_json:
        note = (request.get_json(silent=True) or {}).get("note", "") or ""

    with state_lock:
        if current_monitor is None:
            return jsonify({"error": "No session is running."}), 409
        monitor = current_monitor

    # mark_disruption() calls back into broadcast(), which itself takes
    # state_lock -- so state_lock must be released before calling it, or
    # this thread deadlocks against itself.
    entry = monitor.mark_disruption(note)
    broadcast({"type": "marked_created", "entry": entry})
    return jsonify(entry)


@app.route("/api/sessions/<session_id>/marks/<mark_id>", methods=["PATCH"])
def update_mark(session_id, mark_id):
    note = (request.get_json(silent=True) or {}).get("note", "") if request.is_json else ""

    with state_lock:
        active = current_monitor if (current_monitor and current_monitor.session_id == session_id) else None

    if active is not None:
        entry = active.update_note(mark_id, note)
        if entry is None:
            return jsonify({"error": "Disruption not found."}), 404
        broadcast({"type": "marked_updated", "entry": entry})
        return jsonify(entry)

    entry = storage.update_mark_note(SESSIONS_DIR, session_id, mark_id, note)
    if entry is None:
        return jsonify({"error": "Disruption not found."}), 404
    return jsonify(entry)


@app.route("/api/stream")
def stream():
    q = queue.Queue()
    with state_lock:
        subscribers.append(q)
        snapshot = current_monitor.status() if current_monitor else {"running": False}

    def gen():
        try:
            yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            while True:
                event = q.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            with state_lock:
                if q in subscribers:
                    subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/sessions")
def sessions():
    with state_lock:
        live_summary = summarize(current_monitor.to_dict()) if current_monitor is not None else None

    session_list = storage.list_sessions(SESSIONS_DIR)
    if live_summary is not None:
        # Use the in-memory copy for the running session rather than
        # whatever's on disk -- a session with no events yet hasn't been
        # saved at all, and a running session's on-disk copy can lag
        # slightly behind anyway.
        session_list = [s for s in session_list if s["id"] != live_summary["id"]]
        session_list.insert(0, live_summary)
    return jsonify(session_list)


@app.route("/api/sessions/<session_id>")
def session_detail(session_id):
    with state_lock:
        if current_monitor is not None and current_monitor.session_id == session_id:
            return jsonify(current_monitor.to_dict())

    data = storage.load_session(SESSIONS_DIR, session_id)
    if data is None:
        return jsonify({"error": "Session not found."}), 404
    return jsonify(data)


@app.route("/api/sessions/<session_id>/download")
def session_download(session_id):
    with state_lock:
        if current_monitor is not None and current_monitor.session_id == session_id:
            data = current_monitor.to_dict()
        else:
            data = None
    if data is None:
        data = storage.load_session(SESSIONS_DIR, session_id)
    if data is None:
        return jsonify({"error": "Session not found."}), 404

    bundle = storage.build_download_bundle(data)
    return send_file(
        bundle,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"internet-diagnostic-{session_id}.zip",
    )


def handle_shutdown(signum, frame):
    global current_monitor
    with state_lock:
        monitor = current_monitor
        current_monitor = None
    if monitor is not None:
        monitor.stop()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, threaded=True)
