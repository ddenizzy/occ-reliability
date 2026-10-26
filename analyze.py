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
    return None if not n else xs[n // 2] if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2, 1)


def stats(delays):
    n = len(delays)
    return {"arrivals": n,
            "on_time_pct": pct(sum(EARLY <= d <= LATE for d in delays), n),
            "late_pct": pct(sum(d > LATE for d in delays), n),
            "early_pct": pct(sum(d < EARLY for d in delays), n),
            "median_delay_min": median(delays),
            "p90_delay_min": sorted(delays)[int(0.9 * (n - 1))] if n else None}


def grouped(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r["delay"])
    return groups


def refine_arrivals(db):
    """The logger notices an arrival up to one poll (30 s) late. The GPS track pins it down: find where the bus's path
    first enters a small circle around the stop (or, if no GPS point lands inside, its closest pass) and interpolate
    the time between the two GPS points on either side. Returns {arrival rowid: precise actual datetime}."""
    stops = {(r[0], r[1]): (r[2], r[3]) for r in db.execute("SELECT id, route_id, lat, lng FROM stops")}
    has_gps = "gps_ts" in [c[1] for c in db.execute("PRAGMA table_info(positions)")]
    t_col = "coalesce(gps_ts, ts)" if has_gps else "ts"
    out = {}
    for rowid, vehicle, route, stop, actual in db.execute(
            "SELECT rowid, vehicle, route_id, stop_id, actual FROM arrivals WHERE abs(delay_min) <= 60").fetchall():
        if (stop, route) not in stops:
            continue
        slat, slng = stops[(stop, route)]
        t0 = datetime.fromisoformat(actual).timestamp()
        kx, ky = 111320 * math.cos(math.radians(slat)), 110540   # metres per degree, flat-earth near the stop
        pts = [(t, (lng - slng) * kx, (lat - slat) * ky) for t, lat, lng in db.execute(
            f"SELECT DISTINCT {t_col} t, lat, lng FROM positions WHERE vehicle = ? AND t BETWEEN ? AND ? ORDER BY t",
            (vehicle, t0 - 150, t0 + 5))]
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


def headways(db):
    """Gaps between buses of the same route at the same stop, actual vs timetable. Riders feel these more than lateness:
    two buses together then a long gap ("bunching") means long waits even when each bus is only a little late.
    Expected wait for someone arriving at a random time = E[gap^2] / (2 E[gap])."""
    from datetime import datetime
    seq = {}
    for r in db.execute("SELECT route_id, stop_id, day, scheduled, actual FROM arrivals WHERE abs(delay_min) <= 60 "
                        "ORDER BY route_id, stop_id, day, actual"):
        seq.setdefault((r[0], r[1], r[2]), []).append((datetime.fromisoformat(r[3]), datetime.fromisoformat(r[4])))
    act, sch, bunched = [], [], 0
    for runs in seq.values():
        for (s1, a1), (s2, a2) in zip(runs, runs[1:]):
            planned = (s2 - s1).total_seconds() / 60
            if not 3 <= planned <= 90:   # same trip seen twice, or a service break
                continue
            real = max(0.0, (a2 - a1).total_seconds() / 60)
            act.append(real)
            sch.append(planned)
            bunched += real < 0.25 * planned
    wait = lambda gaps: round(sum(g * g for g in gaps) / (2 * sum(gaps)), 1) if sum(gaps) else None
    return {"gaps": len(act), "bunched_pct": pct(bunched, len(act)),
            "avg_wait_min": wait(act), "avg_wait_if_on_timetable_min": wait(sch),
            "note": "bunched = a bus arrives less than a quarter of the planned gap after the one before"}


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    route_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM routes")}
    stop_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM stops")}
    # an arrival more than an hour off its timetable is a matching error, not a late bus
    precise = refine_arrivals(db)
    rows = []
    for r in db.execute("SELECT rowid, * FROM arrivals WHERE abs(delay_min) <= 60"):
        delay = r["delay_min"]
        if r["rowid"] in precise:
            delay = round((precise[r["rowid"]] - datetime.fromisoformat(r["scheduled"])).total_seconds() / 60, 2)
        rows.append({"route": r["route_id"], "stop": r["stop_id"], "delay": delay, "logged_delay": r["delay_min"],
                     "day": r["day"], "hour": int(r["scheduled"][11:13]), "load": r["load"], "capacity": r["capacity"]})
    if not rows:
        print("No arrivals yet.")
        return
    weekday = lambda r: datetime.fromisoformat(r["day"]).strftime("%A")
    out = {
        "period": [min(r["day"] for r in rows), max(r["day"] for r in rows)],
        "definition": f"on time = {abs(EARLY):g} min early to {LATE:g} min late",
        "overall": stats([r["delay"] for r in rows]),
        "by_route": sorted(({"route": route_name.get(k, str(k)), **stats(v)}
                            for k, v in grouped(rows, lambda r: r["route"]).items() if len(v) >= MIN_OBS),
                           key=lambda x: x["on_time_pct"]),
        "by_hour": [{"hour": k, **stats(v)} for k, v in sorted(grouped(rows, lambda r: r["hour"]).items())],
        "by_weekday": [{"day": k, **stats(v)} for k, v in grouped(rows, weekday).items()],
        "worst_stops": sorted(({"stop": stop_name.get(k, str(k)), **stats(v)}
                               for k, v in grouped(rows, lambda r: r["stop"]).items() if len(v) >= MIN_OBS),
                              key=lambda x: -x["median_delay_min"])[:10],
        "crowding": stats([r["delay"] for r in rows if r["capacity"] and r["load"] / r["capacity"] >= 0.8])
                    | {"note": "arrivals with the bus at least 80% full"},
        "headways": headways(db),
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
