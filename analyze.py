"""On-time performance of OCC buses from the collected data (data/occ.sqlite) -> data/summary.json.

"On time" follows the common transit-industry window: no more than 1 minute early and no more than 5 minutes late.
Usage: python3 analyze.py [database]
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / "occ.sqlite"
EARLY, LATE = -1.0, 5.0
MIN_OBS = 20  # a route, hour or stop needs this many arrivals before it is ranked


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


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    route_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM routes")}
    stop_name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM stops")}
    # an arrival more than an hour off its timetable is a matching error, not a late bus
    rows = [{"route": r["route_id"], "stop": r["stop_id"], "delay": r["delay_min"], "day": r["day"],
             "hour": int(r["scheduled"][11:13]), "load": r["load"], "capacity": r["capacity"]}
            for r in db.execute("SELECT * FROM arrivals WHERE abs(delay_min) <= 60")]
    if not rows:
        print("No arrivals yet.")
        return
    weekday = lambda r: __import__("datetime").date.fromisoformat(r["day"]).strftime("%A")
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
    }
    path = DB.parent / "summary.json"
    path.write_text(json.dumps(out, indent=2))
    o = out["overall"]
    print(f"{o['arrivals']} arrivals, {out['period'][0]} to {out['period'][1]}: {o['on_time_pct']}% on time, "
          f"{o['late_pct']}% late, median delay {o['median_delay_min']} min. Written to {path}")


if __name__ == "__main__":
    main()
