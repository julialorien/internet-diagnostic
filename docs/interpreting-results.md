# Interpreting your results

This monitor pings four things once a second: your **router**, your **modem**, and two public DNS servers (**Cloudflare** `1.1.1.1` and **Google** `8.8.8.8`). Comparing *which* target drops, and *how* the machine running the monitor is connected, is what turns raw ping data into an actual diagnosis.

## Which target drops tells you where the problem is

- **Only Cloudflare/Google drop, router and modem stay up** — the problem is upstream of your house: Comcast's line or your neighborhood node. This is the pattern worth bringing to Comcast, with exact timestamps.
- **Modem drops too, router doesn't** — modem or coax/cable issue.
- **Router drops too** — a local network problem: WiFi, router hardware, or power. This reading is only trustworthy if you were on Ethernet when it happened — see below.

## When multiple targets drop at the same instant

Related targets tend to fail together rather than one at a time — that's a clue about *why*, not a different case from the ones above.

- **Modem, Cloudflare, and Google all drop at once, router stays up** — this is still the "modem or coax/cable issue" case, just visibly so. The modem sits between your router and Comcast's line, so when it loses sync, its own admin interface stops answering *and* everything that needs to route through it to reach the internet stops working, all at the same instant. The router is a separate box on your LAN — it keeps answering pings the whole time, which is exactly why it doesn't drop too.
- That pattern alone can't tell you whether the modem itself is failing or it's losing sync because of a marginal/noisy signal from Comcast — both look identical from the ping log. To tell them apart, check the modem's own admin page (usually `192.168.100.1`) for its event log: repeated "T3" or "T4 timeout" entries around the same timestamps point to a line/signal problem worth escalating to Comcast; an unresponsive modem with no such entries points more toward the modem hardware itself.
- **All four targets, including the router, drop at once** — everything is unreachable simultaneously, which usually means the monitoring machine itself lost its network connection (WiFi disconnected, cable unplugged, laptop slept) rather than a problem with your router, modem, or ISP.

## Why Ethernet matters

Run the monitor on a machine plugged into your router with an Ethernet cable, not over WiFi. Every ping to the router target has to cross whatever link the monitoring machine is using. If that link is WiFi, a dropped ping to the router could mean:

- the router genuinely went down or hung (a real problem), or
- your WiFi adapter had a momentary hiccup — signal fade, interference, a reassociation — which has nothing to do with the router's health or your ISP connection at all.

Both produce an identical-looking "router down" event in the log. Over Ethernet that ambiguity disappears: there's no radio link to blip, so a dropped ping to the router really does mean the router or the wire had a problem. That's what makes the decision tree above trustworthy — it assumes the only thing between the monitoring machine and each target is the thing being tested, not an extra unmonitored hop.

## The app tracks this for you automatically

You don't have to remember or guess which one you were on: the app detects whether the monitoring machine is on Ethernet or WiFi and records it as part of the session. It shows next to the session status while running, appears as a column in History, and is included in every downloaded summary.

It rechecks every 10 seconds and logs a new timestamped entry whenever the connection type changes mid-session — for example if you plug in an Ethernet cable partway through. That makes it possible for a single session to have used both; a session's expanded detail in the History tab shows the full timeline, and rows where this happened are marked "(changed)". If it reports "unknown," it couldn't confidently identify the network interface behind the default route (uncommon, but possible with unusual adapters) — treat "router down" readings from that session with the same caution as a WiFi run.

This detection is macOS-specific (it reads the hardware port list from `networksetup`), consistent with the rest of this app.

## Automatic diagnosis

You don't have to work through the decision tree above by hand. When a session ends, the app applies it automatically and shows the result as a badge in the History tab — this section explains exactly how, so the badge is never a black box.

1. **Group outages into incidents.** Outages starting within 3 seconds of each other, across targets, are treated as one incident — independent per-target ping checks don't detect a shared root cause at the exact same instant, so a little slack is needed to recognize that a modem blip and a Cloudflare blip at "the same time" really are the same event.
2. **Classify each incident** by which targets were involved and, if the router was one of them, what the connection type was at that moment — checked in this order:
   - All four targets at once (router, modem, Cloudflare, Google) → **This machine lost its own connection**.
   - Router involved (with or without others) → **Likely local network issue** if the machine was on Ethernet at the time, otherwise **Possible local or WiFi issue**. Router failures can make the modem unreachable too, so router takes priority over modem when both appear in the same incident.
   - Modem involved (without the router) → **Likely modem or coax issue**.
   - Only Cloudflare and/or Google → **Likely ISP or line issue**.
3. **Pick one dominant category for the whole session:** whichever accounts for the most total downtime across its incidents, ties broken by how many incidents it has, remaining ties broken by whichever happened first in the session.

A session with no outages at all gets **No issues detected** instead of running the steps above.

The badge is deliberately brief — a label and a link. What follows is the fuller explanation and next steps for each one.

### Likely ISP or line issue

Cloudflare and/or Google dropped while the router and modem both stayed up — the same "only Cloudflare/Google drop" pattern described above. The problem is upstream of your house.

**Next steps:** download this session's summary and bring it to Comcast with the exact outage timestamps. Ask specifically about a signal/line check or node congestion in your area — intermittent problems like this often don't show up in Comcast's own remote diagnostics unless someone happens to be looking at the right moment.

### Likely modem or coax issue

The modem dropped — possibly along with Cloudflare and/or Google, but the router stayed up. See "When multiple targets drop at the same instant" above for why the modem and DNS targets tend to go down together.

**Next steps:** check the modem's own admin page (usually `192.168.100.1`) for its event log around the outage timestamps. Repeated T3/T4 timeout entries point to a line/signal problem worth escalating to Comcast; an unresponsive modem with no such entries points more toward the modem hardware itself — worth considering a replacement if it's a few years old.

### Likely local network issue

The router dropped while the monitoring machine was on Ethernet — a trustworthy reading, since there's no WiFi link to introduce ambiguity (see "Why Ethernet matters" above).

**Next steps:** check the router itself — is it warm or overheating, does a reboot help, is it on reliable power? If outages cluster around specific times of day, consider whether something else on the same circuit is involved.

### Possible local or WiFi issue

The router dropped, same as above, but the monitoring machine was on WiFi at the time — so this could be a real router problem, or it could just be the WiFi adapter blipping. The data alone can't tell these apart.

**Next steps:** re-run a session on Ethernet during a similar time window. If the outages disappear, the problem is WiFi-specific (signal, interference, congestion) rather than the router or your ISP — see "If you run over Ethernet and don't see any outages" below.

### This machine lost its own connection

Router, modem, Cloudflare, and Google all dropped at the exact same moment. Everything being unreachable at once usually means the monitoring machine itself disconnected — WiFi turned off, cable unplugged, laptop slept — rather than a real network problem.

**Next steps:** nothing to escalate to your router, modem, or ISP. If this doesn't match what you remember happening at that time, double check the machine wasn't put to sleep or its network toggled off during that window.

### No issues detected

No outages were recorded during this session.

**Next steps:** if you were on Ethernet, this is a clean result — the wired path was fine for the whole session (see "If you run over Ethernet and don't see any outages" below). If you were on WiFi the whole time, this only tested the WiFi-inclusive path; if calls are still dropping, a follow-up session on Ethernet would give a fully conclusive read.

## If you run over Ethernet and don't see any outages

This is itself a useful result, not a dead end. It means the wired path — this machine, your router, your modem, Comcast — was clean for the entire session. If your calls (on a WiFi-connected laptop, say) still drop during that same window, the problem is very likely **WiFi-specific**, not your internet service: signal strength, interference from neighboring networks or 2.4GHz devices, too many devices on the network, or aging WiFi hardware.

That points to a different fix than calling Comcast — router placement, a mesh system, switching the call device to 5GHz, or replacing an old WiFi router, rather than a line issue on Comcast's side.

One caveat: a clean Ethernet run only proves the *wired* path was fine. It doesn't test WiFi at all, so it can't rule out a WiFi problem on whichever device you actually take calls on — it can only make WiFi the prime suspect by elimination.

## If you run over WiFi instead

You can still run the monitor over WiFi — it's better than no data — but treat "router down" events with more suspicion. They might be real router or local-network problems, or they might just be your WiFi adapter blipping, and the log can't tell the two apart. The "only Cloudflare/Google drop" reading is unaffected either way, since that failure mode looks the same regardless of how the monitor is connected.

If you want to specifically test whether WiFi itself is the culprit, the cleanest approach is two runs: one on Ethernet (isolates router/modem/ISP) and one on WiFi, on the same machine, ideally around the same time of day. More outages in the WiFi run than the Ethernet run is a strong signal that WiFi is contributing.
