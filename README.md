# OCC Bus Reliability Study

How on time are Binghamton University's OCC buses? This project records every bus arrival from the public
real-time feed (ETA SPOT, the system behind the ETA Transit app), compares it with the timetable, and measures
on-time performance by route, hour, weekday and stop.

**On time** follows the common transit-industry window: no more than 1 minute early and no more than 5 minutes late.

## How it works

- `logger.py` reads every bus in service every 30 seconds. When a bus's "last served stop" changes, it has just
  served that stop: the time is recorded with the timetable time for that stop, giving one arrival and its delay.
  Buses whose GPS report is more than 3 minutes old are ignored. Standard library only.
- `analyze.py` turns the arrivals into `data/summary.json`: on-time %, late %, median and 90th-percentile delay,
  overall and per route / hour / weekday / stop, and on-time performance when buses are crowded.
- The logger runs on a small always-on server, so the data has no gaps when a laptop sleeps.

## Server setup (once)

1. Create the smallest Ubuntu 24.04 server (any provider; 1 CPU and 1 GB of memory is plenty).
2. On the Mac, make an SSH key if there isn't one: `ssh-keygen -t ed25519` (press Enter for the defaults),
   then paste the contents of `~/.ssh/id_ed25519.pub` into the provider's "SSH keys" box when creating the server.
3. From this folder: `./deploy.sh <server IP>`. It installs the logger as a service that starts on boot and
   restarts itself, a nightly backup (kept 14 days), automatic security updates, and a firewall with only SSH open.

## Getting the data

`./fetch.sh <server IP>` downloads a copy to `data/occ.sqlite`; then `python3 analyze.py`.

## Data

| Table | One row per |
|---|---|
| `arrivals` | bus serving a stop: route, direction, stop, timetable time, actual time, delay (min), load |
| `positions` | bus every 30 s: route, location, last/next stop, the feed's own schedule offset, load |
| `routes`, `stops` | route names and stop locations (refreshed daily) |
