# OCC Bus Reliability Study

How on time are Binghamton University's OCC buses? This project records every bus arrival from the public
real-time feed (ETA SPOT, the system behind the ETA Transit app), compares it with the timetable, and measures
on-time performance by route, hour, weekday and stop.

**On time** follows the common transit-industry window: no more than 1 minute early and no more than 5 minutes late.

## How it works

- `logger.py` reads every bus in service every 30 seconds. When a bus's "last served stop" changes, it has just
  served that stop: the time is recorded with the timetable time for that stop, giving one arrival and its delay.
  Buses whose GPS report is more than 3 minutes old are ignored. Standard library only.
- Arrival times are then sharpened with the GPS track: the logger only notices an arrival up to one poll (30 s)
  late, so `analyze.py` finds where the bus's path enters a 35 m circle around the stop (or its closest pass) and
  interpolates between the two GPS reports on either side. Each position is stored with the bus's own GPS time.
  The timetable itself is in whole minutes, so this is far more precise than the on-time window needs.
- Each timetable time is used once, and only if the stop was still listed ahead of the bus in the last 10 minutes,
  so on loop routes a time left over from an earlier lap can't turn into a fake hour-late arrival.
- Arrivals more than 30 min off the timetable are left out (and counted): the live feed sometimes keeps a bus on
  an earlier trip for a lap (its own on-schedule field says so), then snaps back. About 0.7% on the first day.
- `analyze.py` turns the arrivals into `data/summary.json`: on-time %, late %, median and 90th-percentile delay,
  overall and per route / hour / weekday / stop, on-time performance when buses are crowded, bus bunching
  with the average rider wait (actual vs. what the timetable promises), and how many arrivals were GPS-refined.
  Also: **where buses lose time** (actual minus timetable travel time between consecutive stops), **headway
  regularity** per route (spread of the gaps and the *excess wait time* riders suffer, the London/TfL standard),
  a **route × hour** on-time grid, and **weather** (rain / snow / freezing vs. dry, hourly data from Open-Meteo).
- `report.py` turns `summary.json` into `data/report.html` and `data/report.pdf` with charts (plain SVG, no installs;
  the PDF is printed by Google Chrome).
- The logger runs on a small always-on server, so the data has no gaps when a laptop sleeps.

## Server setup (once)

1. Create the smallest Ubuntu 24.04 server (any provider; 1 CPU and 1 GB of memory is plenty). The study runs on
   an Azure for Students VM (Standard_B2ats_v2, Spain Central: student subscriptions only allow a few regions).
   The scripts log in as `azureuser` and use `sudo`; set `OCC_USER=root` (or another name) for other providers.
2. On the Mac, make an SSH key if there isn't one: `ssh-keygen -t ed25519` (press Enter for the defaults),
   then paste the contents of `~/.ssh/id_ed25519.pub` into the provider's "SSH keys" box when creating the server.
3. From this folder: `./deploy.sh <server IP>`. It installs the logger as a service that starts on boot and
   restarts itself, a nightly backup (kept 14 days), automatic security updates, key-only SSH, a firewall with
   only SSH open, and Tailscale (open the login link it prints).
4. With Tailscale running on the Mac too: `./lockdown.sh occ-logger`. SSH is then closed to the internet and the
   server has no open ports; it is reachable only over Tailscale as `occ-logger`.

## Getting the data

`./fetch.sh occ-logger` downloads a copy to `data/occ.sqlite`; then `python3 analyze.py && python3 report.py`.

## Data

| Table | One row per |
|---|---|
| `arrivals` | bus serving a stop: route, direction, stop, timetable time, actual time, delay (min), load |
| `positions` | bus every 30 s: route, location, last/next stop, the feed's own schedule offset, load, GPS time |
| `routes`, `stops` | route names and stop locations (refreshed daily) |

Developed with AI-assisted programming (Claude Code).
