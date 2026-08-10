const TARGET_LABELS = {
  router: "Router",
  modem: "Modem",
  cloudflare: "Cloudflare DNS",
  google: "Google DNS",
};

const CONNECTION_LABELS = {
  ethernet: "Ethernet",
  wifi: "WiFi",
  unknown: "Connection: unknown",
};

function connectionPillHtml(type) {
  const known = type in CONNECTION_LABELS ? type : "unknown";
  return `<span class="pill pill-${known}">${CONNECTION_LABELS[known]}</span>`;
}

// Maps a diagnosis category to how alarming its badge should look --
// purely presentational, doesn't affect which category gets picked.
const DIAGNOSIS_SEVERITY = {
  isp: "bad",
  modem: "bad",
  local_ethernet: "bad",
  wifi_ambiguous: "warn",
  machine_disconnect: "neutral",
  none: "good",
};

function diagnosisPillHtml(diag) {
  if (!diag) return '<span class="muted">—</span>';
  const severity = DIAGNOSIS_SEVERITY[diag.category] || "neutral";
  return `<a href="#${diag.guide_anchor}" class="diagnosis-link pill pill-diag-${severity}" data-anchor="${diag.guide_anchor}">${diag.label}</a>`;
}

let currentSessionId = null;
let elapsedTimer = null;
let eventSource = null;
let historyPollTimer = null;

// ---- tabs -----------------------------------------------------------

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "history") {
      loadSessions();
    } else {
      clearInterval(historyPollTimer);
    }
    if (btn.dataset.tab === "guide") loadGuide();
  });
});

// ---- guide (rendered from docs/interpreting-results.md, the single
// source of truth also linked from README.md) --------------------------

let guideLoaded = false;

async function loadGuide() {
  if (guideLoaded) return;
  const container = document.getElementById("guide-content");
  try {
    const res = await fetch("/api/guide");
    const md = await res.text();
    container.innerHTML = renderMarkdown(md);
    guideLoaded = true;
  } catch (err) {
    container.innerHTML = '<p class="muted">Could not load the guide.</p>';
  }
}

// Used by diagnosis badges (History tab, live feed) to jump straight to
// the matching explanation in the Guide tab.
async function goToGuideAnchor(anchor) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  document.querySelector('.tab-btn[data-tab="guide"]').classList.add("active");
  document.getElementById("tab-guide").classList.add("active");
  clearInterval(historyPollTimer);

  await loadGuide();

  const target = document.getElementById(anchor);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  target.classList.add("guide-highlight");
  setTimeout(() => target.classList.remove("guide-highlight"), 2000);
}

// Minimal markdown-subset renderer: headings (# ## ###), paragraphs,
// unordered lists (- item), and **bold**/`code` inline. Good enough for
// docs/interpreting-results.md without pulling in a markdown dependency.
// Mirrors diagnosis.py's _slugify() so a diagnosis's guide_anchor always
// matches a real heading id here -- same lowercase/strip/hyphenate rule.
function slugify(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-");
}

function renderMarkdown(md) {
  const inlineFormat = (text) =>
    text
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");

  let html = "";
  let inList = false;
  let para = [];

  const flushPara = () => {
    if (para.length) {
      html += `<p>${inlineFormat(para.join(" "))}</p>`;
      para = [];
    }
  };
  const closeList = () => {
    if (inList) { html += "</ul>"; inList = false; }
  };
  const heading = (level, text) => `<h${level} id="${slugify(text)}">${inlineFormat(text)}</h${level}>`;

  md.split("\n").forEach((raw) => {
    const line = raw.trim();
    if (line === "") { flushPara(); closeList(); return; }
    if (line.startsWith("### ")) { flushPara(); closeList(); html += heading(4, line.slice(4)); return; }
    if (line.startsWith("## ")) { flushPara(); closeList(); html += heading(3, line.slice(3)); return; }
    if (line.startsWith("# ")) { flushPara(); closeList(); html += heading(2, line.slice(2)); return; }
    if (line.startsWith("- ")) {
      flushPara();
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineFormat(line.slice(2))}</li>`;
      return;
    }
    closeList();
    para.push(line);
  });
  flushPara();
  closeList();
  return html;
}

// ---- helpers ----------------------------------------------------------

function formatTs(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString();
}

function formatDuration(seconds) {
  if (seconds == null) return "";
  seconds = Math.round(seconds);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}s`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h === 0) return `${mm}m ${s}s`;
  return `${h}h ${mm}m`;
}

function setBadgeClass(el, status) {
  el.classList.remove("status-up", "status-down", "status-unknown");
  el.classList.add(`status-${status}`);
  el.textContent = status === "up" ? "UP" : status === "down" ? "DOWN" : "…";
}

// ---- live target grid ---------------------------------------------------

function renderTargetGrid(targets, liveStatus) {
  const grid = document.getElementById("target-grid");
  grid.innerHTML = "";
  Object.entries(targets || {}).forEach(([label, host]) => {
    if (!host) return;
    const card = document.createElement("div");
    card.className = "target-card";
    card.innerHTML = `
      <div class="label">${TARGET_LABELS[label] || label}</div>
      <div class="host">${host}</div>
      <span class="status-badge status-unknown" id="badge-${label}">…</span>
    `;
    grid.appendChild(card);
    if (liveStatus && liveStatus[label]) {
      setBadgeClass(document.getElementById(`badge-${label}`), liveStatus[label]);
    }
  });
}

// ---- feed ------------------------------------------------------------

function addFeedItem({ cls, html }) {
  const list = document.getElementById("feed-list");
  const empty = list.querySelector(".feed-empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.className = `feed-item ${cls}`;
  li.innerHTML = html;
  list.prepend(li);
}

function feedItemForEvent(event) {
  const ts = `<span class="ts">${formatTs(event.timestamp)}</span>`;
  if (event.type === "down") {
    return { cls: "down", html: `${ts}<strong>${TARGET_LABELS[event.target] || event.target}</strong> went DOWN` };
  }
  if (event.type === "recovered") {
    return { cls: "recovered", html: `${ts}<strong>${TARGET_LABELS[event.target] || event.target}</strong> recovered` };
  }
  if (event.type === "marked_created") {
    return { cls: "marked", html: markedEntryHtml(event.entry) };
  }
  if (event.type === "connection_changed") {
    return { cls: "session", html: `${ts}Connection changed to ${connectionPillHtml(event.connection_type)}` };
  }
  return null;
}

function markedEntryHtml(entry) {
  const ts = `<span class="ts">${formatTs(entry.timestamp)}</span>`;
  return `
    ${ts}<strong>Disruption marked</strong>
    <div class="note-row" data-mark-id="${entry.id}">
      <input type="text" placeholder="Add a note (e.g. what call, what happened)…" value="${(entry.note || "").replace(/"/g, "&quot;")}" />
      <button class="save-note-btn">Save</button>
    </div>
  `;
}

document.getElementById("feed-list").addEventListener("click", async (e) => {
  const diagLink = e.target.closest(".diagnosis-link");
  if (diagLink) {
    e.preventDefault();
    goToGuideAnchor(diagLink.dataset.anchor);
    return;
  }
  if (!e.target.classList.contains("save-note-btn")) return;
  const row = e.target.closest(".note-row");
  const markId = row.dataset.markId;
  const input = row.querySelector("input");
  await saveNote(currentSessionId, markId, input.value);
  const saved = document.createElement("span");
  saved.className = "note-saved";
  saved.textContent = "Saved";
  row.appendChild(saved);
  setTimeout(() => saved.remove(), 1500);
});

async function saveNote(sessionId, markId, note) {
  await fetch(`/api/sessions/${sessionId}/marks/${markId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

// ---- session state -----------------------------------------------------

function setRunningUI(running, statusData) {
  const stateEl = document.getElementById("session-state");
  const connectionEl = document.getElementById("connection-badge");
  const metaEl = document.getElementById("session-meta");
  const startBtn = document.getElementById("start-btn");
  const stopBtn = document.getElementById("stop-btn");
  const markBtn = document.getElementById("mark-btn");

  if (running) {
    currentSessionId = statusData.session_id;
    stateEl.textContent = "Running";
    stateEl.className = "pill pill-running";
    setConnectionBadge(statusData.connection_type);
    metaEl.textContent = `Session ${statusData.session_id} · started ${formatTs(statusData.started_at)}`;
    startBtn.hidden = true;
    stopBtn.hidden = false;
    markBtn.disabled = false;
    renderTargetGrid(statusData.targets, statusData.live_status);
  } else {
    currentSessionId = null;
    stateEl.textContent = "Idle";
    stateEl.className = "pill pill-idle";
    connectionEl.hidden = true;
    metaEl.textContent = "";
    startBtn.hidden = false;
    stopBtn.hidden = true;
    markBtn.disabled = true;
  }
}

function setConnectionBadge(type) {
  const connectionEl = document.getElementById("connection-badge");
  const known = type in CONNECTION_LABELS ? type : "unknown";
  connectionEl.hidden = false;
  connectionEl.className = `pill pill-${known}`;
  connectionEl.textContent = CONNECTION_LABELS[known];
}

async function fetchStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  setRunningUI(!!data.running, data);
  if (data.running && Array.isArray(data.recent_events)) {
    document.getElementById("feed-list").innerHTML = "";
    data.recent_events.forEach((event) => {
      const item = feedItemForEvent(event);
      if (item) addFeedItem(item);
    });
  }
}

document.getElementById("start-btn").addEventListener("click", async () => {
  const res = await fetch("/api/start", { method: "POST" });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  document.getElementById("feed-list").innerHTML = "";
  setRunningUI(true, data);
});

document.getElementById("stop-btn").addEventListener("click", async () => {
  const res = await fetch("/api/stop", { method: "POST" });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  setRunningUI(false);
});

document.getElementById("mark-btn").addEventListener("click", async () => {
  await fetch("/api/mark", { method: "POST" });
});

// ---- live stream (SSE) -------------------------------------------------

function connectStream() {
  eventSource = new EventSource("/api/stream");

  eventSource.addEventListener("snapshot", (e) => {
    const data = JSON.parse(e.data);
    setRunningUI(!!data.running, data);
    if (data.running && Array.isArray(data.recent_events)) {
      document.getElementById("feed-list").innerHTML = "";
      data.recent_events.forEach((event) => {
        const item = feedItemForEvent(event);
        if (item) addFeedItem(item);
      });
    }
  });

  eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);
    if (event.type === "down" || event.type === "recovered") {
      const badge = document.getElementById(`badge-${event.target}`);
      if (badge) setBadgeClass(badge, event.type === "down" ? "down" : "up");
      addFeedItem(feedItemForEvent(event));
    } else if (event.type === "initial_status") {
      // Just resolves a target's badge from "unknown" to its actual state
      // after the first ping -- not a disruption, so no feed entry.
      const badge = document.getElementById(`badge-${event.target}`);
      if (badge) setBadgeClass(badge, event.status);
    } else if (event.type === "marked_created") {
      addFeedItem(feedItemForEvent(event));
    } else if (event.type === "connection_changed") {
      setConnectionBadge(event.connection_type);
      addFeedItem(feedItemForEvent(event));
    } else if (event.type === "session_ended") {
      setRunningUI(false);
      const diag = event.summary && event.summary.diagnosis;
      const diagSuffix = diag ? ` — ${diagnosisPillHtml(diag)}` : "";
      addFeedItem({ cls: "session", html: `<span class="ts">${formatTs(new Date().toISOString())}</span>Session ended${diagSuffix}` });
    }
  };

  eventSource.onerror = () => {
    // EventSource auto-reconnects; nothing to do here for a local tool.
  };
}

// ---- history -----------------------------------------------------------
// Clicking a row expands its detail inline, directly below that row
// (accordion style: expanding one collapses whichever was open before).

let expandedSessionId = null;

async function loadSessions() {
  const res = await fetch("/api/sessions");
  const sessions = await res.json();
  const tbody = document.getElementById("session-table-body");
  tbody.innerHTML = "";

  if (sessions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="muted">No sessions yet.</td></tr>';
    expandedSessionId = null;
  } else {
    sessions.forEach((s) => tbody.appendChild(buildSessionRow(s)));
    // Re-open whatever was expanded before this refresh (e.g. the 5s poll
    // of a running session) so it doesn't collapse out from under the user.
    if (expandedSessionId && sessions.some((s) => s.id === expandedSessionId)) {
      await expandSession(expandedSessionId);
    } else {
      expandedSessionId = null;
    }
  }

  // Keep a running session's row (duration, outage count) up to date
  // while the History tab is open. Stops itself once nothing is running.
  clearInterval(historyPollTimer);
  if (sessions.some((s) => s.running)) {
    historyPollTimer = setInterval(loadSessions, 5000);
  }
}

function buildSessionRow(s) {
  const totalDowntime = Object.values(s.per_target || {}).reduce((sum, t) => sum + (t.downtime_sec || 0), 0);
  const duration = s.running
    ? formatDuration((Date.now() - new Date(s.started_at)) / 1000)
    : s.ended_at
    ? formatDuration((new Date(s.ended_at) - new Date(s.started_at)) / 1000)
    : "—";
  const startedLabel = s.running
    ? `${formatTs(s.started_at)} <span class="pill pill-running">Running</span>`
    : formatTs(s.started_at);
  const connectionLabel = s.connection_changed
    ? `${connectionPillHtml(s.connection_type)} <span class="muted" title="Connection type changed during this session — expand row for details">(changed)</span>`
    : connectionPillHtml(s.connection_type);

  const tr = document.createElement("tr");
  tr.className = "clickable session-row";
  tr.dataset.sessionId = s.id;
  tr.innerHTML = `
    <td class="expand-arrow">${s.id === expandedSessionId ? "▾" : "▸"}</td>
    <td>${startedLabel}</td>
    <td>${connectionLabel}</td>
    <td>${duration}</td>
    <td>${s.total_outages}</td>
    <td>${formatDuration(totalDowntime)}</td>
    <td>${s.marked_count}</td>
    <td>${diagnosisPillHtml(s.diagnosis)}</td>
    <td><a class="link-btn" href="/api/sessions/${s.id}/download">Download</a></td>
  `;
  tr.addEventListener("click", (e) => {
    const diagLink = e.target.closest(".diagnosis-link");
    if (diagLink) {
      e.preventDefault();
      goToGuideAnchor(diagLink.dataset.anchor);
      return;
    }
    if (e.target.classList.contains("link-btn")) return;
    toggleSession(s.id);
  });
  return tr;
}

async function toggleSession(sessionId) {
  const alreadyOpen = expandedSessionId === sessionId;
  collapseExpandedSession();
  if (!alreadyOpen) {
    await expandSession(sessionId);
  }
}

function collapseExpandedSession() {
  const existing = document.querySelector(".session-detail-row");
  if (existing) existing.remove();
  if (expandedSessionId) {
    const arrow = document.querySelector(`tr[data-session-id="${expandedSessionId}"] .expand-arrow`);
    if (arrow) arrow.textContent = "▸";
  }
  expandedSessionId = null;
}

async function expandSession(sessionId) {
  const row = document.querySelector(`tr[data-session-id="${sessionId}"]`);
  if (!row) return;

  expandedSessionId = sessionId;
  const arrow = row.querySelector(".expand-arrow");
  if (arrow) arrow.textContent = "▾";

  const detailRow = document.createElement("tr");
  detailRow.className = "session-detail-row";
  const cell = document.createElement("td");
  cell.colSpan = 9;
  cell.innerHTML = '<p class="muted">Loading…</p>';
  detailRow.appendChild(cell);
  row.after(detailRow);

  const res = await fetch(`/api/sessions/${sessionId}`);
  const data = await res.json();
  cell.innerHTML = buildSessionDetailHtml(data);

  cell.querySelectorAll(".save-note-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const noteRow = btn.closest(".note-row");
      const markId = noteRow.dataset.markId;
      const input = noteRow.querySelector("input");
      await saveNote(data.id, markId, input.value);
      btn.textContent = "Saved";
      setTimeout(() => (btn.textContent = "Save"), 1500);
    });
  });

  cell.querySelectorAll(".diagnosis-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      goToGuideAnchor(link.dataset.anchor);
    });
  });
}

function connectionTimelineHtml(data) {
  const history = data.connection_history || [];
  if (history.length === 0) return '<p class="muted">Not recorded.</p>';
  return history
    .map((entry, i) => {
      const nextSince = i + 1 < history.length ? history[i + 1].since : null;
      const endLabel = nextSince ? formatTs(nextSince) : data.ended_at ? formatTs(data.ended_at) : "now";
      return `<div class="detail-outage">${connectionPillHtml(entry.type)} from ${formatTs(entry.since)} to ${endLabel}</div>`;
    })
    .join("");
}

function diagnosisSummaryHtml(diag) {
  if (!diag) return '<span class="muted">Diagnosis not available yet.</span>';
  const incidents = diag.incident_count ?? 0;
  const countLabel = incidents === 1 ? "1 incident" : `${incidents} incidents`;
  return `<strong>Diagnosis:</strong> ${diagnosisPillHtml(diag)} <span class="muted">(${countLabel})</span>`;
}

function buildSessionDetailHtml(data) {
  const outagesHtml = (data.outages || []).length
    ? data.outages.map((o) => `
        <div class="detail-outage">
          <strong>${TARGET_LABELS[o.target] || o.target}</strong>
          ${formatTs(o.start)} &rarr; ${o.end ? formatTs(o.end) : "?"}
          (${o.duration_sec != null ? formatDuration(o.duration_sec) : "?"})
        </div>`).join("")
    : '<p class="muted">No outages detected.</p>';

  const marksHtml = (data.marked_disruptions || []).length
    ? data.marked_disruptions.map((m) => `
        <div class="detail-mark">
          <div>${formatTs(m.timestamp)}</div>
          <div class="note-row" data-mark-id="${m.id}">
            <input type="text" value="${(m.note || "").replace(/"/g, "&quot;")}" placeholder="Add a note…" />
            <button class="save-note-btn">Save</button>
          </div>
        </div>`).join("")
    : '<p class="muted">No disruptions marked.</p>';

  return `
    <div class="session-detail-inner">
      <p class="muted">${formatTs(data.started_at)} &rarr; ${data.ended_at ? formatTs(data.ended_at) : "still running"}</p>
      ${data.note_incomplete ? `<p class="muted">${data.note_incomplete}</p>` : ""}
      <p class="diagnosis-summary">${diagnosisSummaryHtml(data.diagnosis)}</p>
      <a class="link-btn" href="/api/sessions/${data.id}/download">Download logs &amp; summary (.zip)</a>
      <h4>Connection</h4>
      ${connectionTimelineHtml(data)}
      <h4>Outages</h4>
      ${outagesHtml}
      <h4>Marked disruptions</h4>
      ${marksHtml}
    </div>
  `;
}

// ---- init --------------------------------------------------------------

fetchStatus();
connectStream();
