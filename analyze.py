"""On-time performance of OCC buses from the collected data (data/occ.sqlite) -> data/summary.json.

"On time" follows the common transit-industry window: no more than 1 minute early and no more than 5 minutes late.
Usage: python3 analyze.py [database]
"""
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / "occ.sqlite"
EARLY, LATE = -1.0, 5.0
MIN_OBS = 20  # a route, hour or stop needs this many arrivals before it is ranked
AT_STOP = 35  # metres: a bus this close to a stop is at it
NEAR = 150    # metres: a GPS track passing farther than this from the stop is not trusted for refining


def pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 2)


def stats(delays):
    n = len(delays)
    return {"arrivals": n,
            "on_time_pct": pct(sum(EARLY <= d <= LATE for d in delays), n),
            "late_pct": pct(sum(d > LATE for d in delays), n),
            "early_pct": pct(sum(d < EARLY for d in delays), n),
            "median_delay_min": median(delays),
            "p90_delay_min": round(sorted(delays)[int(0.9 * (n - 1))], 2) if n else None}


def grouped(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r["delay"])
    return groups


def refine_arrivals(db):
    """The logger notices an arrival up to one poll (30 s) late. The GPS track pins it down: find where the bus's path
    first enters a small circle around the stop (or, if no GPS point lands inside, its closest pass) and interpolate
    the time between the two GPS points on either side. Returns {arrival rowid: precise actual datetime}."""
    import bisect
    stops = {(r[0], r[1]): (r[2], r[3]) for r in db.execute("SELECT id, route_id, lat, lng FROM stops")}
    has_gps = "gps_ts" in [c[1] for c in db.execute("PRAGMA table_info(positions)")]
    t_col = "coalesce(gps_ts, ts)" if has_gps else "ts"
    track = {}   # vehicle -> time-sorted GPS points, read once (one query per arrival took minutes on weeks of data)
    for vehicle, t, lat, lng in db.execute(f"SELECT DISTINCT vehicle, {t_col}, lat, lng FROM positions"):
        track.setdefault(vehicle, []).append((t, lat, lng))
    times = {}
    for vehicle, pts in track.items():
        pts.sort()
        times[vehicle] = [p[0] for p in pts]
    out = {}
    for rowid, vehicle, route, stop, actual in db.execute(
            "SELECT rowid, vehicle, route_id, stop_id, actual FROM arrivals WHERE abs(delay_min) <= 60").fetchall():
        if (stop, route) not in stops or vehicle not in track:
            continue
        slat, slng = stops[(stop, route)]
        t0 = datetime.fromisoformat(actual).timestamp()
        kx, ky = 111320 * math.cos(math.radians(slat)), 110540   # metres per degree, flat-earth near the stop
        ts = times[vehicle]
        window = track[vehicle][bisect.bisect_left(ts, t0 - 150):bisect.bisect_right(ts, t0 + 5)]
        pts = [(t, (lng - slng) * kx, (lat - slat) * ky) for t, lat, lng in window]
        best = None   # (distance, time)
        for (t1, x1, y1), (t2, x2, y2) in zip(pts, pts[1:]):
            dx, dy = x2 - x1, y2 - y1
            seg = dx * dx + dy * dy
            if math.hypot(x1, y1) <= AT_STOP:          # already at the stop at the first point
                best = (0, t1)
                break
            if seg == 0:
                continue
            # where the segment enters the circle: |p1 + u*d| = AT_STOP, smallest u in [0, 1]
            b, c = (x1 * dx + y1 * dy) / seg, (x1 * x1 + y1 * y1 - AT_STOP ** 2) / seg
            disc = b * b - c
            if disc >= 0 and 0 <= -b - math.sqrt(disc) <= 1:
                best = (0, t1 + (-b - math.sqrt(disc)) * (t2 - t1))
                break
            u = min(1, max(0, -b))                      # otherwise the segment's closest pass
            d = math.hypot(x1 + u * dx, y1 + u * dy)
            if d <= NEAR and (best is None or d < best[0]):
                best = (d, t1 + u * (t2 - t1))
        if best:
            out[rowid] = datetime.fromtimestamp(best[1])
    return out


def wait(gaps):
    """Average wait for a rider arriving at a random time, given the gaps between buses: E[gap^2] / (2 E[gap])."""
    return round(sum(g * g for g in gaps) / (2 * sum(gaps)), 1) if sum(gaps) else None


def headways(rows, route_name):
    """Gaps between buses of the same route at the same stop, actual vs timetable. Riders feel these more than lateness:
    two buses together then a long gap ("bunching") means long waits even when each bus is only a little late.
    Excess wait time (EWT, the London/TfL standard) = actual average wait - the wait the timetable promises."""
    seq = {}
    for r in sorted(rows, key=lambda r: r["actual"]):
        seq.setdefault((r["route"], r["stop"], r["day"]), []).append((r["scheduled"], r["actual"]))
    per_route = {}
    for (route, _, _), runs in seq.items():
        for (s1, a1), (s2, a2) in zip(runs, runs[1:]):
            planned = (s2 - s1).total_seconds() / 60
            if not 3 <= planned <= 90:   # same trip seen twice, or a service break
                continue
            per_route.setdefault(route, []).append((max(0.0, (a2 - a1).total_seconds() / 60), planned))

    def summarize(pairs):
        act, sch = [a for a, _ in pairs], [s for _, s in pairs]
        mean = sum(act) / len(act)
        sd = (sum((a - mean) ** 2 for a in act) / len(act)) ** 0.5
        w, ws = wait(act), wait(sch)
        return {"gaps": len(pairs), "bunched_pct": pct(sum(a < 0.25 * s for a, s in pairs), len(pairs)),
                "headway_cv": round(sd / mean, 2) if mean else None,
                "avg_wait_min": w, "avg_wait_if_on_timetable_min": ws,
                "excess_wait_min": round(w - ws, 1) if w is not None and ws is not None else None}

    every = [x for pairs in per_route.values() for x in pairs]
    if not every:
        return {"gaps": 0}
    return summarize(every) | {
        "by_route": sorted(({"route": route_name.get(k, str(k)), **summarize(v)}
                            for k, v in per_route.items() if len(v) >= MIN_OBS), key=lambda x: -x["excess_wait_min"]),
        "note": "bunched = a bus arrives less than a quarter of the planned gap after the one before; headway_cv = "
                "spread of the gaps (0 = perfectly even; above ~0.5 riders notice); excess wait = extra minutes "
                "riders wait compared with buses running exactly on the timetable"}


def segments(rows, route_name, stop_name):
    """Where buses lose time: for each pair of consecutive stops served by the same bus, actual travel time minus
    timetable travel time. Positive = the timetable is too tight there (traffic, a long hill, a busy stop)."""
    by_bus = {}
    for r in rows:
        by_bus.setdefault((r["vehicle"], r["route"], r["block"], r["day"]), []).append(r)
    seg = {}
    for runs in by_bus.values():
        runs.sort(key=lambda r: r["actual"])
        for a, b in zip(runs, runs[1:]):
            planned = (b["scheduled"] - a["scheduled"]).total_seconds() / 60
            real = (b["actual"] - a["actual"]).total_seconds() / 60
            if a["stop"] == b["stop"] or not 0 <= planned <= 20 or not 0 < real <= 30:   # layover, gap in the data
                continue
            seg.setdefault((a["route"], a["stop"], b["stop"]), []).append(real - planned)
    out = []
    for (route, s1, s2), lost in seg.items():
        if len(lost) >= MIN_OBS:
            out.append({"route": route_name.get(route, str(route)), "from": stop_name.get(s1, str(s1)),
                        "to": stop_name.get(s2, str(s2)), "trips": len(lost),
                        "avg_min_lost": round(sum(lost) / len(lost), 2), "median_min_lost": median(lost)})
    return {"worst": sorted(out, key=lambda x: -x["avg_min_lost"])[:10],
            "best": sorted(out, key=lambda x: x["avg_min_lost"])[:5],
            "note": "minutes lost = actual minus timetable travel time between two consecutive stops; the timetable is "
                    "in whole minutes, so single trips are noisy and only stop pairs with enough trips are listed"}


def hour_route_grid(rows, route_name):
    """On-time % for every route and hour (cells with fewer than 5 arrivals left out)."""
    grid = {}
    for (route, hour), v in grouped(rows, lambda r: (r["route"], r["hour"])).items():
        if len(v) >= 5:
            grid.setdefault(route_name.get(route, str(route)), {})[hour] = stats(v)["on_time_pct"]
    return grid


def weather(rows, cache):
    """On-time performance by weather. Hourly rain, snow and temperature for Binghamton from Open-Meteo (free, no
    key), cached in data/weather.json. Snow = any snowfall that hour; rain = at least 0.2 mm; otherwise dry."""
    import urllib.request
    days = sorted({r["day"] for r in rows})
    data = json.loads(cache.read_text()) if cache.exists() else {}
    if not all(f"{d}T{h:02d}" in data for d in days for h in (0, 23)):
        url = ("https://api.open-meteo.com/v1/forecast?latitude=42.09&longitude=-75.97&timezone=America%2FNew_York"
               f"&hourly=precipitation,snowfall,temperature_2m&start_date={days[0]}&end_date={days[-1]}")
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                h = json.loads(resp.read())["hourly"]
            data.update({t[:13]: [p, s, c] for t, p, s, c in
                         zip(h["time"], h["precipitation"], h["snowfall"], h["temperature_2m"])})
            cache.write_text(json.dumps(data))
        except Exception as e:  # offline or the service changed: the rest of the analysis still runs
            return {"note": f"weather unavailable ({e.__class__.__name__})"}

    def kind(r):
        p, s, c = data.get(f"{r['day']}T{r['hour']:02d}") or [None] * 3
        if p is None:
            return None
        return "snow" if (s or 0) > 0 else "rain" if p >= 0.2 else "freezing (dry)" if c is not None and c <= 0 else "dry"

    out = {k: stats(v) for k, v in grouped(rows, kind).items() if k}
    return out | {"note": "hourly weather at Binghamton (Open-Meteo); rain = 0.2 mm or more in that hour"}


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    route_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM routes")}
    stop_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM stops")}
    # an arrival more than an hour off its timetable is a matching error, not a late bus
    precise = refine_arrivals(db)
    rows = []
    for r in db.execute("SELECT rowid, * FROM arrivals WHERE abs(delay_min) <= 60"):
        scheduled = datetime.fromisoformat(r["scheduled"])
        actual = precise.get(r["rowid"]) or datetime.fromisoformat(r["actual"])
        rows.append({"route": r["route_id"], "stop": r["stop_id"], "vehicle": r["vehicle"], "block": r["block"],
                     "day": r["day"], "hour": scheduled.hour, "scheduled": scheduled, "actual": actual,
                     "delay": round((actual - scheduled).total_seconds() / 60, 2), "logged_delay": r["delay_min"],
                     "load": r["load"], "capacity": r["capacity"]})
    if not rows:
        print("No arrivals yet.")
        return
    weekday = lambda r: datetime.fromisoformat(r["day"]).strftime("%A")
    days = sorted({r["day"] for r in rows})
    out = {
        "period": [days[0], days[-1]],
        "days_of_data": len(days),
        "buses_seen": len({r["vehicle"] for r in rows}),
        "routes_seen": len({r["route"] for r in rows}),
        "definition": f"on time = {abs(EARLY):g} min early to {LATE:g} min late",
        "overall": stats([r["delay"] for r in rows]),
        "by_route": sorted(({"route": route_name.get(k, str(k)), **stats(v)}
                            for k, v in grouped(rows, lambda r: r["route"]).items() if len(v) >= MIN_OBS),
                           key=lambda x: x["on_time_pct"]),
        "by_hour": [{"hour": k, **stats(v)} for k, v in sorted(grouped(rows, lambda r: r["hour"]).items())],
        "by_weekday": [{"day": k, **stats(v)} for k, v in grouped(rows, weekday).items()],
        "hour_route_on_time_pct": hour_route_grid(rows, route_name),
        "worst_stops": sorted(({"stop": stop_name.get(k, str(k)), **stats(v)}
                               for k, v in grouped(rows, lambda r: r["stop"]).items() if len(v) >= MIN_OBS),
                              key=lambda x: -x["median_delay_min"])[:10],
        "segments": segments(rows, route_name, stop_name),
        "headways": headways(rows, route_name),
        "weather": weather(rows, DB.parent / "weather.json"),
        "crowding": stats([r["delay"] for r in rows if r["capacity"] and r["load"] / r["capacity"] >= 0.8])
                    | {"note": "arrivals with the bus at least 80% full (the feed reported load 0 for every bus in "
                               "the first data, so this may stay empty)"},
        "timing": {"refined_from_gps_pct": pct(len(precise), len(rows)),
                   "median_correction_sec": median([round(60 * (r["logged_delay"] - r["delay"])) for r in rows]),
                   "note": "arrival times re-estimated from the GPS track; the rest use the time the logger noticed"},
    }
    path = DB.parent / "summary.json"
    path.write_text(json.dumps(out, indent=2))
    o = out["overall"]
    print(f"{o['arrivals']} arrivals, {out['period'][0]} to {out['period'][1]}: {o['on_time_pct']}% on time, "
          f"{o['late_pct']}% late, median delay {o['median_delay_min']} min. Written to {path}")


if __name__ == "__main__":
    main()
