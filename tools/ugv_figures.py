#!/usr/bin/env python3
"""Figures for docs/ugv.md from one ground-robot patrol log (standard library only).

  python3 tools/ugv_figures.py run/ugv/<time> [--out docs/media]

Writes two SVG files:
  ugv-patrol-top.svg  the forest from above with the true path, the SLAM position and wheel odometry alone, the
                      fence faults, and two close-ups: where SLAM was furthest off, and back at the start
  ugv-error.svg       position error along the patrol for GNSS, wheel odometry and SLAM (mean per 5 m travelled)

Errors are computed the way tools/ugv_eval.py computes them: each estimate against the true pose nearest in time.
The forest comes from worlds/forest_meta.json (./ugv.sh generates it).
"""
import argparse
import json
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from ugv_eval import patrols                        # noqa: E402  (the same patrol window as the scores)
FONT = 'font-family="system-ui, -apple-system, Segoe UI, sans-serif"'
# reference chart palette, slots 1-3 (light / dark), plus ink and chrome
LIGHT = dict(bg="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
             slam="#2a78d6", odom="#eb6834", gnss="#1baf7a")
DARK = dict(bg="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835",
            slam="#3987e5", odom="#d95926", gnss="#199e70")
FAULT = "#d03b3b"                                   # status "critical"
FAULT_NAMES = {"wire_break": "broken wire", "branch_short": "branch on the wires", "post_down": "fallen post"}


def load(run):
    rows = [json.loads(line) for line in open(os.path.join(run, "log.jsonl")) if line.strip()]
    meta = json.load(open(os.path.join(ROOT, "worlds", "forest_meta.json")))
    t0, t1 = patrols(rows)[-1][:2]                  # the last patrol in the log, as tools/ugv_eval.py scores it
    win = [r for r in rows if t0 <= r["wall"] <= t1]
    truth = [r for r in win if r["k"] == "truth"]
    sx, sy, syaw = meta["spawn"]
    c, s = math.cos(syaw), math.sin(syaw)
    odom = [dict(wall=r["wall"], x=sx + c * r["x"] - s * r["y"], y=sy + s * r["x"] + c * r["y"])
            for r in win if r["k"] == "odom"]
    slam = [r for r in win if r["k"] == "pose" and r.get("src") == "slam"]
    gnss = [r for r in win if r["k"] == "gps" and r.get("mode", 0) >= 2]
    return rows, meta, truth, odom, slam, gnss


def against_truth(truth, est, err=None):
    """(index of the true pose nearest in time, error in m) for each estimate."""
    out, j = [], 0
    for r in est:
        while j + 1 < len(truth) and truth[j + 1]["wall"] <= r["wall"]:
            j += 1
        e = r[err] if err else math.hypot(r["x"] - truth[j]["x"], r["y"] - truth[j]["y"])
        out.append((j, e))
    return out


def thin(pts, step):
    """Keep a point every `step` metres (and the last one)."""
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= step:
            out.append(p)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def poly(pts, tf, **attr):
    d = " ".join("%.1f,%.1f" % tf(x, y) for x, y in pts)
    a = " ".join('%s="%s"' % (k.replace("_", "-"), v) for k, v in attr.items())
    return '<polyline points="%s" fill="none" stroke-linejoin="round" stroke-linecap="round" %s/>' % (d, a)


def scene(meta, truth_xy, slam_xy, odom_xy, tf, k, box=None, marks=()):
    """The forest and the three paths, drawn through transform tf (metres -> px) at k px per metre."""
    out = []
    x0, y0, x1, y1 = box or (-1e9, -1e9, 1e9, 1e9)
    inside = lambda x, y, m=0: x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m
    for cx, cy, r, _h in meta["crowns"]:
        if inside(cx, cy, r):
            px, py = tf(cx, cy)
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#cfe0c6"/>' % (px, py, r * k))
    for cx, cy, r, _h in meta["crowns"]:
        if inside(cx, cy):
            px, py = tf(cx, cy)
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#7d9a6c"/>' % (px, py, max(1.0, 0.22 * k)))
    posts = meta["fence_posts"]
    out.append(poly(posts + posts[:1], tf, stroke="#a8803c", stroke_width="%.1f" % max(1.2, 0.08 * k)))
    for x, y in posts:
        if inside(x, y):
            px, py = tf(x, y)
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#7a5a2a"/>' % (px, py, max(1.3, 0.12 * k)))
    w = 2.0 if k < 10 else 3.0
    out.append(poly(odom_xy, tf, stroke=LIGHT["odom"], stroke_width=w))
    out.append(poly(slam_xy, tf, stroke=LIGHT["slam"], stroke_width=w + 1.5))
    out.append(poly(truth_xy, tf, stroke=LIGHT["ink"], stroke_width=1.2 if k < 10 else 1.6))
    sx, sy, syaw = meta["spawn"]
    if inside(sx, sy):
        px, py = tf(sx, sy)
        a = -syaw
        tri = [(px + 9 * math.cos(a), py + 9 * math.sin(a)),
               (px + 7 * math.cos(a + 2.5), py + 7 * math.sin(a + 2.5)),
               (px + 7 * math.cos(a - 2.5), py + 7 * math.sin(a - 2.5))]
        out.append('<polygon points="%s" fill="%s" stroke="#fcfcfb" stroke-width="2"/>'
                   % (" ".join("%.1f,%.1f" % p for p in tri), LIGHT["ink"]))
        out.append('<text x="%.1f" y="%.1f" %s font-size="13" font-weight="600" fill="%s">start</text>'
                   % (px - 14, py + 24, FONT, LIGHT["ink"]))
    for f in meta["faults"]:
        if inside(f["x"], f["y"]):
            px, py = tf(f["x"], f["y"])
            out.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="#fcfcfb" stroke-width="2"/>'
                       % (px, py, FAULT))
            out.append('<text x="%.1f" y="%.1f" %s font-size="13" font-weight="600" fill="%s">%s</text>'
                       % (px + 10, py + 5, FONT, LIGHT["ink"], f["id"]))
    for (ax, ay), (bx, by), label in marks:           # an estimate and the true position at the same moment
        pa, pb = tf(ax, ay), tf(bx, by)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>'
                   % (pa[0], pa[1], pb[0], pb[1], LIGHT["ink"]))
        for p in (pa, pb):
            out.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" stroke="#fcfcfb" stroke-width="2"/>'
                       % (p[0], p[1], LIGHT["ink"]))
        mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
        out.append('<text x="%.1f" y="%.1f" %s font-size="13" font-weight="600" fill="%s" paint-order="stroke" '
                   'stroke="#fcfcfb" stroke-width="4">%s</text>' % (mx + 10, my - 8, FONT, LIGHT["ink"], label))
    return out


def legend_item(x, y, kind, color, label):
    if kind == "line":
        sw = '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % (
            x, y, x + 22, y, color)
    elif kind == "dot":
        sw = '<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (x + 11, y, color)
    else:
        sw = '<circle cx="%d" cy="%d" r="8" fill="#cfe0c6"/><circle cx="%d" cy="%d" r="2" fill="#7d9a6c"/>' % (
            x + 11, y, x + 11, y)
    txt = '<text x="%d" y="%d" %s font-size="14" fill="%s">%s</text>' % (x + 30, y + 5, FONT, LIGHT["ink"], label)
    return sw + txt, x + 30 + int(7.4 * len(label)) + 26


def top_view(meta, truth, odom, slam, out_path, date):
    W, pad = 1200, 8.0
    xs = [p[0] for p in meta["fence_posts"]]
    ys = [p[1] for p in meta["fence_posts"]]
    bx0, bx1, by0, by1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    k = W / (bx1 - bx0)
    head = 56
    map_h = (by1 - by0) * k
    tf = lambda x, y: ((x - bx0) * k, head + (by1 - y) * k)
    truth_xy = thin([(r["x"], r["y"]) for r in truth], 0.25)
    slam_xy = thin([(r["x"], r["y"]) for r in slam], 0.25)
    odom_xy = thin([(r["x"], r["y"]) for r in odom], 0.25)

    # close-up 1: where SLAM was furthest from the truth; close-up 2: back at the start (the end of the patrol)
    se = against_truth(truth, slam)
    i = max(range(len(se)), key=lambda n: se[n][1])
    t_worst = truth[se[i][0]]
    oe = against_truth(truth, odom)
    t_end, o_end, s_end = truth[oe[-1][0]], odom[-1], slam[-1]
    s_end_err = se[-1][1]
    zooms = [
        ("1", "Where SLAM was furthest off: %.2f m" % se[i][1], (t_worst["x"], t_worst["y"]),
         [((slam[i]["x"], slam[i]["y"]), (t_worst["x"], t_worst["y"]), "SLAM %.2f m" % se[i][1])]),
        ("2", "Back at the start: odometry %.1f m off, SLAM %.2f m" % (oe[-1][1], s_end_err), (t_end["x"], t_end["y"]),
         [((o_end["x"], o_end["y"]), (t_end["x"], t_end["y"]), "odometry %.1f m" % oe[-1][1])]),
    ]
    zw_m, zh_m, zk = 26.0, 17.0, 22.0                  # close-up window in m, and px per m
    zw, zh = zw_m * zk, zh_m * zk
    gap = (W - 2 * zw) / 3
    zy = head + map_h + 46
    H = int(zy + zh + 40)

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H),
           '<title>Ground robot patrol from above: true path, SLAM position and wheel odometry</title>',
           '<rect width="%d" height="%d" rx="10" fill="#f4f2ea"/>' % (W, H)]
    x = 16
    for kind, color, label in (("line", LIGHT["ink"], "true path (simulator)"),
                               ("line", LIGHT["slam"], "SLAM position (Jetson)"),
                               ("line", LIGHT["odom"], "wheel odometry alone"),
                               ("dot", FAULT, "fence fault"), ("tree", None, "tree crown")):
        s, x = legend_item(x, 28, kind, color, label)
        svg.append(s)
    svg.append('<text x="%d" y="33" text-anchor="end" %s font-size="13" fill="%s">repeat patrol %s</text>'
               % (W - 16, FONT, LIGHT["ink2"], date))
    svg.append('<clipPath id="m"><rect x="0" y="%d" width="%d" height="%.0f"/></clipPath><g clip-path="url(#m)">'
               % (head, W, map_h))
    svg += scene(meta, truth_xy, slam_xy, odom_xy, tf, k)
    svg.append("</g>")
    for n, (tag, _title, (cx, cy), _m) in enumerate(zooms):     # close-up frames on the main map
        ax, ay = tf(cx - zw_m / 2, cy + zh_m / 2)
        svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="%s" stroke-width="1.5"/>'
                   % (ax, ay, zw_m * k, zh_m * k, LIGHT["ink"]))
        svg.append('<text x="%.1f" y="%.1f" %s font-size="14" font-weight="700" fill="%s">%s</text>'
                   % (ax + 4, ay - 5, FONT, LIGHT["ink"], tag))
    # scale bar
    sb_x, sb_y = 20, head + map_h - 18
    svg.append('<rect x="%d" y="%.0f" width="%.0f" height="22" rx="4" fill="#f4f2ea" opacity="0.85"/>'
               % (sb_x - 6, sb_y - 14, 20 * k + 50))
    svg.append('<line x1="%d" y1="%.0f" x2="%.1f" y2="%.0f" stroke="%s" stroke-width="2"/>'
               % (sb_x, sb_y, sb_x + 20 * k, sb_y, LIGHT["ink"]))
    svg.append('<text x="%.1f" y="%.0f" %s font-size="13" fill="%s">20 m</text>'
               % (sb_x + 20 * k + 8, sb_y + 4, FONT, LIGHT["ink"]))
    for n, (tag, title, (cx, cy), marks) in enumerate(zooms):
        ox = gap + n * (zw + gap)
        zx0, zy0 = cx - zw_m / 2, cy - zh_m / 2
        ztf = lambda x, y, ox=ox, zx0=zx0, zy0=zy0: (ox + (x - zx0) * zk, zy + (zy0 + zh_m - y) * zk)
        svg.append('<text x="%.1f" y="%.1f" %s font-size="14" font-weight="600" fill="%s">%s  %s</text>'
                   % (ox, zy - 10, FONT, LIGHT["ink"], tag, title))
        svg.append('<clipPath id="z%d"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6"/></clipPath>'
                   % (n, ox, zy, zw, zh))
        svg.append('<g clip-path="url(#z%d)"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#f4f2ea"/>'
                   % (n, ox, zy, zw, zh))
        svg += scene(meta, truth_xy, slam_xy, odom_xy, ztf, zk, (zx0, zy0, zx0 + zw_m, zy0 + zh_m), marks)
        svg.append("</g>")
        svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="none" stroke="%s" '
                   'stroke-width="1.5"/>' % (ox, zy, zw, zh, LIGHT["ink"]))
        svg.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                   % (ox + 12, zy + zh - 14, ox + 12 + 5 * zk, zy + zh - 14, LIGHT["ink"]))
        svg.append('<text x="%.1f" y="%.1f" %s font-size="13" fill="%s" paint-order="stroke" stroke="#f4f2ea" '
                   'stroke-width="4">5 m</text>' % (ox + 20 + 5 * zk, zy + zh - 10, FONT, LIGHT["ink"]))
    svg.append("</svg>")
    open(out_path, "w").write("\n".join(svg) + "\n")


def error_chart(truth, odom, slam, gnss, out_path, date, summary):
    # distance travelled at each true pose
    dist = [0.0]
    for a, b in zip(truth, truth[1:]):
        dist.append(dist[-1] + math.hypot(b["x"] - a["x"], b["y"] - a["y"]))
    step = 5.0
    series = {}
    for name, est, err in (("gnss", gnss, "err_m"), ("odom", odom, None), ("slam", slam, None)):
        bins = {}
        for j, e in against_truth(truth, est, err):
            bins.setdefault(int(dist[j] // step), []).append(e)
        series[name] = [((b + 0.5) * step, statistics.fmean(v)) for b, v in sorted(bins.items())]
    W, H = 1200, 460
    L, R, T, B = 56, 250, 96, 48
    xmax = dist[-1]                                  # the axis ends where the patrol ended
    ymax = math.ceil(max(v for s in series.values() for _, v in s) / 2) * 2
    px = lambda d: L + d / xmax * (W - L - R)
    py = lambda e: T + (1 - e / ymax) * (H - T - B)
    css = "".join(
        [".bg{fill:%s}.ink{fill:%s}.ink2{fill:%s}.muted{fill:%s}.grid{stroke:%s}.axis{stroke:%s}" % (
            LIGHT["bg"], LIGHT["ink"], LIGHT["ink2"], LIGHT["muted"], LIGHT["grid"], LIGHT["axis"])] +
        [".%s{stroke:%s}.f%s{fill:%s}" % (n, LIGHT[n], n, LIGHT[n]) for n in ("slam", "odom", "gnss")] +
        ["@media (prefers-color-scheme: dark){"] +
        [".bg{fill:%s}.ink{fill:%s}.ink2{fill:%s}.muted{fill:%s}.grid{stroke:%s}.axis{stroke:%s}" % (
            DARK["bg"], DARK["ink"], DARK["ink2"], DARK["muted"], DARK["grid"], DARK["axis"])] +
        [".%s{stroke:%s}.f%s{fill:%s}" % (n, DARK[n], n, DARK[n]) for n in ("slam", "odom", "gnss")] + ["}"])
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H),
           '<title>Position error along one patrol: GNSS, wheel odometry and SLAM</title>',
           "<style>%s</style>" % css,
           '<rect class="bg" width="%d" height="%d" rx="10"/>' % (W, H),
           '<text class="ink" x="%d" y="32" %s font-size="17" font-weight="600">How far each position estimate was '
           'from the truth</text>' % (L, FONT),
           '<text class="ink2" x="%d" y="54" %s font-size="13">Repeat patrol %s, %.0f m forest loop. Metres off the '
           'true position, averaged over every 5 m travelled.</text>' % (L, FONT, date, dist[-1])]
    labels = {"slam": "SLAM", "odom": "wheel odometry", "gnss": "GNSS"}
    x = L
    for n in ("slam", "odom", "gnss"):
        svg.append('<line class="%s" x1="%d" y1="76" x2="%d" y2="76" stroke-width="3" stroke-linecap="round"/>'
                   % (n, x, x + 20))
        svg.append('<text class="ink" x="%d" y="81" %s font-size="13">%s</text>' % (x + 28, FONT, labels[n]))
        x += 28 + int(7.2 * len(labels[n])) + 28
    for e in range(0, ymax + 1, 2):
        svg.append('<line class="%s" x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke-width="1"/>'
                   % ("axis" if e == 0 else "grid", L, py(e), W - R, py(e)))
        svg.append('<text class="muted" x="%d" y="%.1f" text-anchor="end" %s font-size="12">%d m</text>'
                   % (L - 8, py(e) + 4, FONT, e))
    for d in range(0, int(xmax) + 1, 100):
        svg.append('<text class="muted" x="%.1f" y="%d" text-anchor="middle" %s font-size="12">%d m</text>'
                   % (px(d), H - B + 20, FONT, d))
    svg.append('<text class="muted" x="%d" y="%d" text-anchor="end" %s font-size="12">distance travelled</text>'
               % (W - R, H - 8, FONT))
    for n in ("gnss", "odom", "slam"):
        pts = " ".join("%.1f,%.1f" % (px(d), py(e)) for d, e in series[n])
        svg.append('<polyline class="%s" points="%s" fill="none" stroke-width="2" stroke-linejoin="round" '
                   'stroke-linecap="round"/>' % (n, pts))
    # direct labels at the line ends, kept at least 34 px apart
    g, o, s = summary["gnss"], summary["odom_drift_m"], summary["slam"]
    texts = {"gnss": ("GNSS under the trees", "median %.1f m, p95 %.1f m" % (g["error_m"]["median"], g["error_m"]["p95"])),
             "odom": ("wheel odometry alone", "%.1f m off at the end" % o["end"]),
             "slam": ("SLAM on the Jetson", "median %.2f m, max %.2f m" % (s["median"], s["max"]))}
    ends = sorted(((py(series[n][-1][1]), n) for n in texts), key=lambda t: t[0])
    placed = []
    for y, n in ends:
        if placed and y < placed[-1][0] + 34:
            y = placed[-1][0] + 34
        placed.append((y, n))
    over = placed[-1][0] - (H - B)
    if over > 0:
        placed = [(y - over, n) for y, n in placed]
    for y, n in placed:
        ex, ey = px(series[n][-1][0]), py(series[n][-1][1])
        svg.append('<circle class="f%s" cx="%.1f" cy="%.1f" r="4" stroke="%s" stroke-width="2"/>'
                   % (n, ex, ey, LIGHT["bg"]))
        svg.append('<text class="ink" x="%.1f" y="%.1f" %s font-size="13" font-weight="600">%s</text>'
                   % (W - R + 16, y - 2, FONT, texts[n][0]))
        svg.append('<text class="ink2" x="%.1f" y="%.1f" %s font-size="12">%s</text>'
                   % (W - R + 16, y + 14, FONT, texts[n][1]))
    svg.append("</svg>")
    open(out_path, "w").write("\n".join(svg) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run/ugv/<time> folder with log.jsonl (and summary.json from tools/ugv_eval.py)")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "media"))
    a = ap.parse_args()
    rows, meta, truth, odom, slam, gnss = load(a.run)
    if not slam:
        raise SystemExit("no SLAM poses in this run (run it with pose:=slam)")
    p = json.load(open(os.path.join(a.run, "summary.json")))["patrols"][-1]
    summary = {"gnss": p["gnss"], "odom_drift_m": p["odom_drift_m"], "slam": p["localisation_error_m"]["slam"]}
    stamp = os.path.basename(os.path.normpath(a.run))
    date = "%s-%s-%s %s:%s" % (stamp[:4], stamp[4:6], stamp[6:8], stamp[9:11], stamp[11:13])
    os.makedirs(a.out, exist_ok=True)
    top_view(meta, truth, odom, slam, os.path.join(a.out, "ugv-patrol-top.svg"), date)
    error_chart(truth, odom, slam, gnss, os.path.join(a.out, "ugv-error.svg"), date, summary)
    print("wrote", os.path.join(a.out, "ugv-patrol-top.svg"), "and", os.path.join(a.out, "ugv-error.svg"))


if __name__ == "__main__":
    main()
