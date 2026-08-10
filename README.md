# Internet Diagnostic Monitor

A small local web app for tracking down intermittent internet dropouts
(e.g. Zoom/Google Meet calls cutting out). It continuously pings your
router, your modem, and two public DNS servers, records exactly when and
where connectivity drops, and lets you flag "a call just dropped" in the
moment so you can correlate it with what the network was actually doing.

**Run it on a machine plugged into your router with an Ethernet cable, not
WiFi** — see [docs/interpreting-results.md](docs/interpreting-results.md)
for why that matters, what it means if you don't see any outages while on
Ethernet, and how to read the results in general. The same content is
available from the app's **Guide** tab once it's running.

## Running it

Requires Python 3. From the repo root:

```
./run.sh
```

First run creates a virtualenv in `.venv/` and installs Flask into it;
later runs reuse it. It starts the server at `http://127.0.0.1:5055` and
opens it in your browser automatically. Leave the terminal window open —
closing it (or Ctrl+C) stops the server and cleanly ends any running
session.

To run it manually instead:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
cd app && python3 server.py
```

## Using the app

**Live tab**

<img width="940" height="682" alt="image" src="https://github.com/user-attachments/assets/e62a4259-d57a-400a-9037-9ddebf07b2d2" />

- **Start Monitoring** begins a session: it pings your router, modem, and
  `1.1.1.1` / `8.8.8.8` once a second and shows a live UP/DOWN badge for
  each. It also detects and displays whether this machine is currently on
  Ethernet or WiFi — see
  [docs/interpreting-results.md](docs/interpreting-results.md) for why that
  matters.
- When something drops, it shows up immediately in the live feed with a
  timestamp, and the badge for that target turns red until it recovers.
- **Mark Disruption Now** — hit this the moment you notice a call glitch or
  drop, even if you're not sure yet whether it's your internet. It records
  the exact time. You can type a note right away or leave it blank and add
  one later (e.g. "Zoom call with client, audio froze for ~10s").
- **Stop Monitoring** ends the session and saves it to history.

**History tab**

<img width="919" height="428" alt="image" src="https://github.com/user-attachments/assets/ef24ef77-855f-48ad-9b22-e51cc28bd2ad" />

- Lists every past session with its connection type (Ethernet/WiFi),
  duration, outage count, total downtime, how many disruptions you marked,
  and an automatic **diagnosis** — the single most likely culprit (ISP,
  modem, local network, WiFi, or "this machine lost its connection"),
  worked out from the outages and connection type recorded during the
  session. A currently running session shows up here too, tagged "Running"
  (diagnosis only runs once a session ends).

<img width="897" height="402" alt="image" src="https://github.com/user-attachments/assets/585aab1f-fcd7-4fec-8342-019c8858229b" />
  
- The diagnosis badge is deliberately brief — click it (or the arrow to
  expand the row) to jump straight to the matching explanation and
  suggested next steps on the **Guide** tab. See
  [docs/interpreting-results.md](docs/interpreting-results.md#automatic-diagnosis)
  for exactly how it decides, so the badge is never a black box.
- Click a row to expand its full detail inline: the diagnosis, connection
  timeline, every outage window (target, start, end, duration), and every
  marked disruption, with notes you can add or edit at any time. Click
  again to collapse it.
- **Download** on any session gets you a `.zip` with:
  - `summary.txt` — plain-English summary (including the diagnosis),
    readable by a Comcast rep
  - `events.csv` — the same data in spreadsheet form
  - `raw.json` — full underlying data

## How it works, briefly

There's no database — each session is just a JSON file under `data/sessions/`.
The backend (`app/server.py`, Flask) runs one background thread per target
that pings it every second; when a ping stops succeeding it opens an
"outage" window, and closes it when pings resume. The Live tab connects to
the server over Server-Sent Events (`/api/stream`) so updates appear as
they happen without polling. None of this data leaves your machine.

## The underlying ping monitor (CLI)

`netwatch.sh` in the repo root is the original terminal-only version of the
same idea — same targets, same up/down logic, no UI, no saved history.
Useful if you just want a quick terminal check without starting the app:

```
./netwatch.sh
```
