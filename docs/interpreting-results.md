# Interpreting your results

This monitor pings four things once a second: your **router**, your **modem**, and two public DNS servers (**Cloudflare** `1.1.1.1` and **Google** `8.8.8.8`). Comparing *which* target drops, and *how* the machine running the monitor is connected, is what turns raw ping data into an actual diagnosis.

## Which target drops tells you where the problem is

- **Only Cloudflare/Google drop, router and modem stay up** — the problem is upstream of your house: Comcast's line or your neighborhood node. This is the pattern worth bringing to Comcast, with exact timestamps.
- **Modem drops too, router doesn't** — modem or coax/cable issue.
- **Router drops too** — a local network problem: WiFi, router hardware, or power. This reading is only trustworthy if you were on Ethernet when it happened — see below.

## Why Ethernet matters

Run the monitor on a machine plugged into your router with an Ethernet cable, not over WiFi. Every ping to the router target has to cross whatever link the monitoring machine is using. If that link is WiFi, a dropped ping to the router could mean:

- the router genuinely went down or hung (a real problem), or
- your WiFi adapter had a momentary hiccup — signal fade, interference, a reassociation — which has nothing to do with the router's health or your ISP connection at all.

Both produce an identical-looking "router down" event in the log. Over Ethernet that ambiguity disappears: there's no radio link to blip, so a dropped ping to the router really does mean the router or the wire had a problem. That's what makes the decision tree above trustworthy — it assumes the only thing between the monitoring machine and each target is the thing being tested, not an extra unmonitored hop.

## If you run over Ethernet and don't see any outages

This is itself a useful result, not a dead end. It means the wired path — this machine, your router, your modem, Comcast — was clean for the entire session. If your calls (on a WiFi-connected laptop, say) still drop during that same window, the problem is very likely **WiFi-specific**, not your internet service: signal strength, interference from neighboring networks or 2.4GHz devices, too many devices on the network, or aging WiFi hardware.

That points to a different fix than calling Comcast — router placement, a mesh system, switching the call device to 5GHz, or replacing an old WiFi router, rather than a line issue on Comcast's side.

One caveat: a clean Ethernet run only proves the *wired* path was fine. It doesn't test WiFi at all, so it can't rule out a WiFi problem on whichever device you actually take calls on — it can only make WiFi the prime suspect by elimination.

## If you run over WiFi instead

You can still run the monitor over WiFi — it's better than no data — but treat "router down" events with more suspicion. They might be real router or local-network problems, or they might just be your WiFi adapter blipping, and the log can't tell the two apart. The "only Cloudflare/Google drop" reading is unaffected either way, since that failure mode looks the same regardless of how the monitor is connected.

If you want to specifically test whether WiFi itself is the culprit, the cleanest approach is two runs: one on Ethernet (isolates router/modem/ISP) and one on WiFi, on the same machine, ideally around the same time of day. More outages in the WiFi run than the Ethernet run is a strong signal that WiFi is contributing.
