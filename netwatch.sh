#!/usr/bin/env bash
# Continuous ping monitor to localize intermittent internet drops.
#
# Pings your router, your modem, and two public DNS servers in parallel,
# once a second, and prints DOWN/RECOVERED lines with timestamps as they
# happen. Run this in a terminal during a video call; when the call drops,
# check which target(s) went down at that same timestamp:
#   - only the public IPs (cloudflare/google) drop  -> Comcast's line/node
#   - modem also drops, router doesn't               -> modem/coax issue
#   - router drops too                                -> local network/WiFi
#
# Usage:
#   ./netwatch.sh
#   MODEM_IP=192.168.100.1 ./netwatch.sh   # override if your modem uses a different admin IP
#
# Press Ctrl+C to stop; it prints a summary of every outage window found.

set -uo pipefail

INTERVAL=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGDIR"
RUN_ID="$(date +%Y%m%d_%H%M%S)"

GATEWAY="$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')"
MODEM="${MODEM_IP:-192.168.100.1}"

LABELS=(router modem cloudflare google)
HOSTS=("$GATEWAY" "$MODEM" "1.1.1.1" "8.8.8.8")

echo "Detected router/gateway: ${GATEWAY:-not found}"
echo "Modem IP: $MODEM (override with MODEM_IP=x.x.x.x ./netwatch.sh if wrong)"
echo "Logging to: $LOGDIR/netwatch_${RUN_ID}_<label>.csv"
echo "Press Ctrl+C to stop and see a summary."
echo

PIDS=()

monitor_target() {
  local label="$1" host="$2"
  local logfile="$LOGDIR/netwatch_${RUN_ID}_${label}.csv"
  echo "timestamp,label,host,status,latency_ms" > "$logfile"
  local was_up=1
  local outage_start_ts=""

  while true; do
    local ts out latency status
    ts="$(date '+%Y-%m-%d %H:%M:%S')"

    if out=$(ping -c 1 -W 1000 "$host" 2>/dev/null); then
      latency=$(echo "$out" | sed -n 's/.*time=\([0-9.]*\).*/\1/p')
      status="up"
      if [[ "$was_up" -eq 0 ]]; then
        printf "[%s] %-10s RECOVERED (was down since %s) host=%s\n" "$ts" "$label" "$outage_start_ts" "$host"
        was_up=1
      fi
    else
      latency=""
      status="down"
      if [[ "$was_up" -eq 1 ]]; then
        outage_start_ts="$ts"
        printf "[%s] %-10s DOWN host=%s\n" "$ts" "$label" "$host"
        was_up=0
      fi
    fi

    echo "${ts},${label},${host},${status},${latency}" >> "$logfile"
    sleep "$INTERVAL"
  done
}

for i in "${!LABELS[@]}"; do
  label="${LABELS[$i]}"
  host="${HOSTS[$i]}"
  if [[ -z "$host" ]]; then
    echo "Skipping $label (no host resolved)"
    continue
  fi
  monitor_target "$label" "$host" &
  PIDS+=($!)
done

summarize() {
  echo
  echo "===== Outage windows ====="
  for i in "${!LABELS[@]}"; do
    label="${LABELS[$i]}"
    host="${HOSTS[$i]}"
    [[ -z "$host" ]] && continue
    logfile="$LOGDIR/netwatch_${RUN_ID}_${label}.csv"
    [[ -f "$logfile" ]] || continue

    echo "--- $label ($host) ---"
    awk -F',' '
      NR==1 { next }
      {
        ts=$1; status=$4
        if (status=="down" && prev!="down") { start=ts }
        if (status=="up" && prev=="down") { print "  " start "  ->  " ts }
        prev=status
      }
      END { if (prev=="down") print "  " start "  ->  (still down when stopped)" }
    ' "$logfile"

    total=$(tail -n +2 "$logfile" | wc -l | tr -d ' ')
    downs=$(tail -n +2 "$logfile" | awk -F',' '$4=="down"' | wc -l | tr -d ' ')
    echo "  ($downs/$total pings failed)"
  done
  echo
  echo "Full logs: $LOGDIR/netwatch_${RUN_ID}_*.csv"
}

cleanup() {
  echo
  echo "Stopping monitors..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
  summarize
  exit 0
}

trap cleanup INT TERM
wait
