"""Turns a finished session's outages + connection history into a single
"most likely culprit" diagnosis, shown as a badge in the History tab.

This is a formal version of the manual decision tree documented in
docs/interpreting-results.md's "Automatic diagnosis" section -- the two
must stay in sync. If you change the grouping window, the classification
order, or the ranking rule below, update that doc to match.
"""
import re
from datetime import datetime

# Outages starting within this many seconds of each other (across targets)
# are treated as one incident, since independently-running per-target ping
# loops don't detect a shared root cause at the exact same instant.
INCIDENT_GROUP_WINDOW_SEC = 3

_LABELS = {
    "isp": "Likely ISP or line issue",
    "modem": "Likely modem or coax issue",
    "local_ethernet": "Likely local network issue",
    "wifi_ambiguous": "Possible local or WiFi issue",
    "machine_disconnect": "This machine lost its own connection",
    "none": "No issues detected",
}


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"\s+", "-", text)


# Single source for both the brief label shown in the UI and the anchor
# linking to the matching heading in docs/interpreting-results.md --
# derived from the label itself so they can't drift apart.
CULPRITS = {
    category: {"label": label, "guide_anchor": _slugify(label)}
    for category, label in _LABELS.items()
}


def _parse_epoch(iso_ts):
    return datetime.fromisoformat(iso_ts).timestamp()


def _connection_type_at(connection_history, timestamp):
    current = "unknown"
    for entry in connection_history:
        if entry["since"] <= timestamp:
            current = entry["type"]
        else:
            break
    return current


def _group_into_incidents(outages):
    ordered = sorted(outages, key=lambda o: o["start"])
    incidents = []
    for outage in ordered:
        start_epoch = _parse_epoch(outage["start"])
        if incidents and start_epoch - incidents[-1]["_last_start"] <= INCIDENT_GROUP_WINDOW_SEC:
            incidents[-1]["outages"].append(outage)
            incidents[-1]["_last_start"] = start_epoch
        else:
            incidents.append({"outages": [outage], "_last_start": start_epoch})
    return incidents


def _classify_incident(targets, connection_type):
    if targets == {"router", "modem", "cloudflare", "google"}:
        return "machine_disconnect"
    # Router failures can make the modem unreachable too (it's reached
    # through the router), so router takes priority over modem when both
    # are involved in the same incident.
    if "router" in targets:
        return "local_ethernet" if connection_type == "ethernet" else "wifi_ambiguous"
    if "modem" in targets:
        return "modem"
    if targets <= {"cloudflare", "google"}:
        return "isp"
    return "none"


def diagnose(data):
    """Full diagnosis for a finished session: category, label, guide_anchor,
    incident_count, and a per-category breakdown. Meaningless for a session
    that's still running (there's no fixed connection_history to reason
    about yet), so callers should only invoke this once ended_at is set."""
    outages = data.get("outages", [])
    connection_history = data.get("connection_history", [])

    incidents = _group_into_incidents(outages)
    if not incidents:
        return {"category": "none", "incident_count": 0, "breakdown": {}, **CULPRITS["none"]}

    tally = {}
    for incident in incidents:
        targets = {o["target"] for o in incident["outages"]}
        incident_start = min(o["start"] for o in incident["outages"])
        connection_type = _connection_type_at(connection_history, incident_start)
        category = _classify_incident(targets, connection_type)
        downtime = sum(o.get("duration_sec") or 0 for o in incident["outages"])
        bucket = tally.setdefault(category, {"count": 0, "downtime_sec": 0.0})
        bucket["count"] += 1
        bucket["downtime_sec"] += downtime

    # Ranked by total downtime, ties broken by incident count, remaining
    # ties broken by insertion order (i.e. whichever occurred first --
    # Python dicts preserve the order categories were first seen above).
    top_category = max(tally, key=lambda c: (tally[c]["downtime_sec"], tally[c]["count"]))
    breakdown = {
        cat: {"count": v["count"], "downtime_sec": round(v["downtime_sec"], 1)}
        for cat, v in tally.items()
    }

    return {
        "category": top_category,
        "incident_count": len(incidents),
        "breakdown": breakdown,
        **CULPRITS[top_category],
    }


def diagnose_or_default(data):
    """The session's saved diagnosis if it has one, else computed fresh for
    an already-ended session, else None for a still-running session."""
    if data.get("diagnosis"):
        return data["diagnosis"]
    if data.get("ended_at") is None:
        return None
    return diagnose(data)
