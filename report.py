"""Turns data/summary.json (from analyze.py) into a readable report with charts: data/report.html and data/report.pdf.

Charts are plain SVG written here, so nothing needs installing. The PDF is printed by Google Chrome if it is installed.
Usage: python3 report.py [summary.json]
"""
import html
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

SUMMARY = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / "summary.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
GREEN, AMBER, BLUE, GREY = "#2e9e5b", "#e08a1e", "#3f7fe0", "#c9ccd1"
esc = lambda x: html.escape(str(x))


def fmt(x, unit=""):
    return "–" if x is None else f"{x:g}{unit}" if isinstance(x, (int, float)) else esc(x)


def stacked_bars(rows, label):
    """One horizontal bar per row: on time (green) / late (amber) / early (blue), in %."""
    h, w, left = 22, 640, 210
    parts = [f'<svg viewBox="0 0 {w} {len(rows) * h + 24}" width="100%" role="img">']
    for i, r in enumerate(rows):
        y, x = i * h, left
        parts.append(f'<text x="{left - 8}" y="{y + 15}" text-anchor="end" font-size="11">{esc(r[label])}</text>')
        for key, col in (("on_time_pct", GREEN), ("late_pct", AMBER), ("early_pct", BLUE)):
            bw = (w - left - 125) * (r.get(key) or 0) / 100
            parts.append(f'<rect x="{x:.1f}" y="{y + 3}" width="{bw:.1f}" height="{h - 6}" fill="{col}"/>')
            x += bw
        parts.append(f'<text x="{x + 6:.1f}" y="{y + 15}" font-size="10" fill="#555">{fmt(r.get("on_time_pct"), "%")}'
                     f' · n={r["arrivals"]}</text>')
    y = len(rows) * h + 16
    for i, (name, col) in enumerate((("on time", GREEN), ("late", AMBER), ("early", BLUE))):
        parts.append(f'<rect x="{left + i * 90}" y="{y - 9}" width="10" height="10" fill="{col}"/>'
                     f'<text x="{left + i * 90 + 14}" y="{y}" font-size="10">{name}</text>')
    return "".join(parts) + "</svg>"


def hour_chart(rows):
    """On-time % (bars) and median delay (line) by scheduled hour."""
    if not rows:
        return ""
    w, h, pad = 640, 200, 34
    step = (w - 2 * pad) / len(rows)
    parts = [f'<svg viewBox="0 0 {w} {h + 30}" width="100%" role="img">',
             f'<line x1="{pad}" y1="{h}" x2="{w - pad}" y2="{h}" stroke="#999"/>']
    top = max(10, max((r["median_delay_min"] or 0) for r in rows))
    line = []
    for i, r in enumerate(rows):
        x = pad + i * step
        bh = (h - 10) * (r["on_time_pct"] or 0) / 100
        parts.append(f'<rect x="{x + 2:.1f}" y="{h - bh:.1f}" width="{step - 4:.1f}" height="{bh:.1f}" fill="{GREEN}" '
                     f'opacity=".75"><title>{r["hour"]}:00 · {r["on_time_pct"]}% on time · n={r["arrivals"]}</title></rect>')
        parts.append(f'<text x="{x + step / 2:.1f}" y="{h + 14}" text-anchor="middle" font-size="10">{r["hour"]}</text>')
        line.append(f'{x + step / 2:.1f},{h - (h - 10) * max(0, r["median_delay_min"] or 0) / top:.1f}')
    parts.append(f'<polyline points="{" ".join(line)}" fill="none" stroke="{AMBER}" stroke-width="2.5"/>')
    parts.append(f'<text x="{pad}" y="{h + 28}" font-size="10" fill="#555">hour of day · green bars = % on time '
                 f'(0–100) · orange line = median delay (0–{top:g} min)</text>')
    return "".join(parts) + "</svg>"


def heatmap(grid):
    """Routes x hours, cell colour = on-time % (red low, green high)."""
    if not grid:
        return "<p class=small>Not enough arrivals per route and hour yet.</p>"
    hours = sorted({int(hh) for row in grid.values() for hh in row})
    cw, ch, left = 30, 20, 210
    parts = [f'<svg viewBox="0 0 {left + cw * len(hours) + 10} {ch * len(grid) + 26}" width="100%" role="img">']
    for j, hh in enumerate(hours):
        parts.append(f'<text x="{left + j * cw + cw / 2}" y="12" text-anchor="middle" font-size="10">{hh}</text>')
    for i, (route, row) in enumerate(sorted(grid.items())):
        y = 18 + i * ch
        parts.append(f'<text x="{left - 8}" y="{y + 14}" text-anchor="end" font-size="11">{esc(route)}</text>')
        for j, hh in enumerate(hours):
            v = row.get(str(hh), row.get(hh))
            if v is None:
                continue
            hue = 120 * v / 100   # 0 = red, 120 = green
            parts.append(f'<rect x="{left + j * cw + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" '
                         f'fill="hsl({hue:.0f},60%,55%)"><title>{esc(route)} {hh}:00 · {v}% on time</title></rect>'
                         f'<text x="{left + j * cw + cw / 2}" y="{y + 14}" text-anchor="middle" font-size="9" '
                         f'fill="#fff">{v:.0f}</text>')
    return "".join(parts) + "</svg>"


def table(rows, cols):
    head = "".join(f"<th>{esc(c)}</th>" for c, _ in cols)
    body = "".join("<tr>" + "".join(f"<td>{fmt(r.get(k))}</td>" for _, k in cols) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>" if rows else "<p class=small>Not enough data yet.</p>"


def main():
    s = json.loads(SUMMARY.read_text())
    o, hw, seg, wx = s["overall"], s.get("headways", {}), s.get("segments", {}), s.get("weather", {})
    days = s.get("days_of_data", 1)
    caution = ("" if days >= 14 else f'<div class=warn><b>Early data ({days} day{"s" if days != 1 else ""}).</b> '
               "Numbers can still swing a lot; the study needs 2–3 weeks.</div>")
    wx_rows = [{"weather": k, **v} for k, v in wx.items() if isinstance(v, dict)]
    out = f"""<!doctype html><html><head><meta charset="utf-8"><title>OCC Bus Reliability Report</title><style>
body{{font:10.5pt/1.45 -apple-system,Helvetica,Arial,sans-serif;color:#1d1d1f;max-width:7.2in;margin:0 auto;padding:.3in 0}}
h1{{font-size:20pt;margin:0}}h2{{font-size:13pt;margin:22px 0 6px;border-bottom:1px solid #ddd;padding-bottom:3px;
break-after:avoid}}.sub,.small{{color:#666}}.small{{font-size:9pt}}svg{{break-inside:avoid}}
.warn{{background:#fff6e0;border-left:4px solid #e6a100;padding:8px 12px;margin:12px 0}}
.kpi{{display:flex;gap:8px;margin:10px 0}}.kpi div{{flex:1;background:#f5f5f7;border-radius:6px;padding:8px;text-align:center}}
.kpi b{{display:block;font-size:16pt}}table{{border-collapse:collapse;width:100%;font-size:9.5pt;margin:6px 0;
break-inside:avoid}}th,td{{padding:3px 6px;border-bottom:1px solid #eee;text-align:left}}th{{background:#f5f5f7}}
</style></head><body>
<h1>OCC Bus Reliability Report</h1>
<div class=sub>Data {esc(s["period"][0])} to {esc(s["period"][1])} · {days} day(s) · {s.get("buses_seen", "?")} buses ·
{s.get("routes_seen", "?")} routes · generated {date.today().isoformat()}</div>
{caution}
<div class=kpi><div><b>{o["arrivals"]:,}</b>stop arrivals</div><div><b>{fmt(o["on_time_pct"], "%")}</b>on time</div>
<div><b>{fmt(o["late_pct"], "%")}</b>late</div><div><b>{fmt(o["early_pct"], "%")}</b>early</div>
<div><b>{fmt(o["median_delay_min"], " min")}</b>median delay</div><div><b>{fmt(hw.get("excess_wait_min"), " min")}</b>
extra wait per rider</div></div>
<p class=small>{esc(s["definition"])}. Arrival times are refined from the GPS track for
{fmt(s.get("timing", {}).get("refined_from_gps_pct"), "%")} of arrivals. Left out: {s.get("left_out", {}).get("arrivals", 0)}
arrivals ({fmt(s.get("left_out", {}).get("pct"), "%")}), {esc(s.get("left_out", {}).get("note", ""))}.</p>

<h2>On time by route</h2>{stacked_bars(s["by_route"], "route") if s["by_route"] else "<p class=small>No route has enough arrivals yet.</p>"}
<h2>By hour of day</h2>{hour_chart(s["by_hour"])}
<h2>Route × hour (% on time)</h2>{heatmap(s.get("hour_route_on_time_pct", {}))}
<h2>By weekday</h2>{stacked_bars(s["by_weekday"], "day")}

<h2>Where buses lose time</h2>
<p class=small>{esc(seg.get("note", ""))}</p>
{table(seg.get("worst", []), [("Route", "route"), ("From", "from"), ("To", "to"), ("Trips", "trips"),
                              ("Avg min lost", "avg_min_lost"), ("Median", "median_min_lost")])}

<h2>Gaps between buses (what riders feel)</h2>
<p>Average wait at a stop: <b>{fmt(hw.get("avg_wait_min"), " min")}</b> vs. <b>{fmt(hw.get("avg_wait_if_on_timetable_min"), " min")}</b>
if buses ran exactly on the timetable. Bunched gaps: {fmt(hw.get("bunched_pct"), "%")}. Headway spread (CV):
{fmt(hw.get("headway_cv"))}.</p>
{table(hw.get("by_route", []), [("Route", "route"), ("Gaps", "gaps"), ("Spread (CV)", "headway_cv"),
                                ("Wait (min)", "avg_wait_min"), ("Timetable wait", "avg_wait_if_on_timetable_min"),
                                ("Extra wait", "excess_wait_min"), ("Bunched %", "bunched_pct")])}
<p class=small>{esc(hw.get("note", ""))}</p>

<h2>Worst stops</h2>
{table(s.get("worst_stops", []), [("Stop", "stop"), ("Arrivals", "arrivals"), ("On time %", "on_time_pct"),
                                   ("Median delay", "median_delay_min"), ("90th pct delay", "p90_delay_min")])}

<h2>Weather</h2>
{stacked_bars(wx_rows, "weather") if wx_rows else f'<p class=small>{esc(wx.get("note", "No weather data."))}</p>'}
<p class=small>{esc(wx.get("note", ""))}</p>
<p class=small>Code: github.com/ddenizzy/occ-reliability · Data: OCC Transport public ETA SPOT feed · Weather: Open-Meteo.</p>
</body></html>"""
    page = SUMMARY.parent / "report.html"
    page.write_text(out)
    pdf = SUMMARY.parent / "report.pdf"
    if Path(CHROME).exists():
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        page.as_uri()], capture_output=True, timeout=120)
    print(f"Report: {page}" + (f" and {pdf}" if pdf.exists() else " (install Google Chrome for the PDF)"))


if __name__ == "__main__":
    main()
