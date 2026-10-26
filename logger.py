"""Collects OCC Transport (Binghamton University buses) on-time data from the public ETA SPOT feed.

Every POLL seconds it reads every bus in service. Each bus reports the last stop it served and, for every stop
ahead, the timetable time and the live expected time. When a bus's "last stop" changes, it has just served that
stop: we record the moment and compare it with the timetable time we last saw for that stop. That gives one
observed arrival with its delay in minutes.

Only the standard library is used, so it runs on the Mac's built-in Python. Data goes to data/occ.sqlite.
"""
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://binghamtonupublic.etaspot.net/service.php"
POLL = 30            # seconds between reads; gentle on a public feed
STALE = 180          # a bus whose GPS report is older than this is ignored ("ghost" buses at night)
DB = Path(__file__).parent / "data" / "occ.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS arrivals (
  ts INTEGER, day TEXT, route_id INTEGER, direction TEXT, vehicle TEXT, block INTEGER,
  stop_id INTEGER, pattern_stop INTEGER, scheduled TEXT, actual TEXT, delay_min REAL,
  load INTEGER, capacity INTEGER,
  UNIQUE (vehicle, pattern_stop, scheduled));
CREATE TABLE IF NOT EXISTS positions (
  ts INTEGER, route_id INTEGER, vehicle TEXT, lat REAL, lng REAL, last_stop INTEGER, next_stop INTEGER,
  on_schedule INTEGER, load INTEGER, gps_ts REAL);
CREATE TABLE IF NOT EXISTS routes (id INTEGER PRIMARY KEY, name TEXT, abbr TEXT, color TEXT);
CREATE TABLE IF NOT EXISTS stops (id INTEGER, route_id INTEGER, name TEXT, lat REAL, lng REAL,
  PRIMARY KEY (id, route_id));
"""


def get(service, **params):
    q = urllib.parse.urlencode({"service": service, "token": "TESTING", **params})
    req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "occ-reliability-study/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())[service]


def clock_near(text, when):
    """'06:23PM' -> the datetime with that clock time closest to `when` (handles trips across midnight)."""
    try:
        t = datetime.strptime(text.strip(), "%I:%M%p")
    except (ValueError, AttributeError):
        return None
    base = when.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return min((base + timedelta(days=d) for d in (-1, 0, 1)), key=lambda c: abs((c - when).total_seconds()))


def save_reference(db):
    for r in get("get_routes"):
        db.execute("INSERT OR REPLACE INTO routes VALUES (?,?,?,?)",
                   (r["id"], r.get("name"), r.get("abbr"), r.get("color")))
    for s in get("get_stops"):
        db.execute("INSERT OR REPLACE INTO stops VALUES (?,?,?,?,?)", (s["id"], s["rid"], s["name"], s["lat"], s["lng"]))
    db.commit()


def main():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    if "gps_ts" not in [c[1] for c in db.execute("PRAGMA table_info(positions)")]:   # databases from before gps_ts
        db.execute("ALTER TABLE positions ADD COLUMN gps_ts REAL")
    seen = {}       # vehicle -> {"last": pattern stop id, "sched": {pattern stop id: timetable text}}
    ref_day = None
    while True:
        try:
            today = datetime.now().date()
            if ref_day != today:          # routes and stops, once a day
                save_reference(db)
                ref_day = today
            now = time.time()
            for v in get("get_vehicles", includeETAData=1, inService=1, orderedETAArray=1):
                if not v.get("inService") or now - (v.get("receiveTime") or 0) / 1000 > STALE:
                    continue
                vid, ps = str(v.get("equipmentID")), v.get("lastPatternStopID")
                db.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (int(now), v["routeID"], vid, v["lat"], v["lng"], v.get("lastStopID"),
                            v.get("nextStopID"), v.get("onSchedule"), v.get("load"), v["receiveTime"] / 1000))
                mem = seen.setdefault(vid, {"last": ps, "sched": {}})
                if ps != mem["last"] and ps in mem["sched"]:
                    actual = datetime.fromtimestamp(v["receiveTime"] / 1000)
                    sched = clock_near(mem["sched"][ps], actual)
                    if sched:
                        db.execute("INSERT OR IGNORE INTO arrivals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (int(now), actual.strftime("%Y-%m-%d"), v["routeID"], v.get("directionAbbr"), vid,
                                    v.get("blockID"), v.get("lastStopID"), ps, sched.isoformat(timespec="minutes"),
                                    actual.isoformat(timespec="seconds"),
                                    round((actual - sched).total_seconds() / 60, 1), v.get("load"), v.get("capacity")))
                mem["last"] = ps
                for s in v.get("minutesToNextStops") or []:   # remember the timetable time of every stop ahead
                    if s.get("schedule"):
                        mem["sched"][s["patternStopID"]] = s["schedule"]
            db.commit()
        except Exception as e:  # network hiccup or feed change: note it and keep going
            print(datetime.now().isoformat(timespec="seconds"), "error:", repr(e)[:200], flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
