"""Scores ground robot patrols from tools/ugv_relay.py's log (run/ugv/<time>/log.jsonl), against the simulator's truth.

For each patrol (from the patrol node's "driving" to "done", "blocked" or "stopped", or the end of the log):
  - route: completion (truth projected on the route), time, mean speed, cross-track error (truth to route)
  - localisation: wheel odometry drift against the truth (end, max, per 100 m), and the error of every pose the
    Jetson logged through the relay (the SLAM pose): median, p95, max, at the end
  - GNSS: fix availability, 3D share, error (median, p95) overall and by sky cover (open, partial, dense canopy)
  - faults: which ones passed through the side camera's view (left side, within 50 degrees of its axis, closer than
    6 m), and for how long
  - obstacle stops (from the patrol node)

  python3 tools/ugv_eval.py                 the newest log
  python3 tools/ugv_eval.py run/ugv/<time>  a given run; --json writes summary.json next to the log
"""
import argparse
import glob
import json
import math
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "worlds", "forest_meta.json")


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def r2(x):
    return None if x is None else round(x, 2)


def project(route, cum, x, y, start, window=80):
    """Index and distance of the route point closest to (x, y), searching forward from start."""
    best, bi = 1e18, start
    for i in range(start, min(len(route) - 1, start + window)):
        (ax, ay), (bx, by) = route[i], route[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        d = math.hypot(x - ax - t * dx, y - ay - t * dy)
        if d < best:
            best, bi = d, i
    return bi, best


def patrols(rows):
    """[(t0, t1, pose_topic, final_status)] from the patrol node's events."""
    out, cur = [], None
    for r in rows:
        if r.get("k") == "event" and r.get("src") == "patrol":
            st = r.get("state")
            if st == "driving" and cur is None:
                cur = [r["wall"], None, r.get("pose_topic"), r]
            elif st in ("done", "blocked", "stopped", "restarting", "idle") and cur is not None:
                cur[1], cur[3] = r["wall"], r
                out.append(tuple(cur))
                cur = None
        elif r.get("k") == "reset" and cur is not None:
            cur[1] = r["wall"]
            out.append(tuple(cur))
            cur = None
    if cur is not None:
        cur[1] = rows[-1]["wall"]
        out.append(tuple(cur))
    return out


def score(rows, meta, t0, t1, pose_topic, final):
    route = meta["route"]
    cum = [0.0]
    for (ax, ay), (bx, by) in zip(route, route[1:]):
        cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
    win = [r for r in rows if t0 <= r["wall"] <= t1]
    truth = [r for r in win if r["k"] == "truth"]
    odom = [r for r in win if r["k"] == "odom"]
    gps = [r for r in win if r["k"] == "gps"]
    if not truth:
        return None
    idx, xte, travelled = 0, [], 0.0
    for a, b in zip(truth, truth[1:]):
        travelled += math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    for r in truth:
        idx, d = project(route, cum, r["x"], r["y"], idx)
        xte.append(d)
    done_m = cum[idx]
    dur = truth[-1]["wall"] - truth[0]["wall"]
    # odometry (odom frame, from the spawn pose) in the map frame, against the nearest truth sample in time
    sx, sy, syaw = meta["spawn"]
    c, s = math.cos(syaw), math.sin(syaw)
    drift, j = [], 0
    for o in odom:
        while j + 1 < len(truth) and truth[j + 1]["wall"] <= o["wall"]:
            j += 1
        mx, my = sx + c * o["x"] - s * o["y"], sy + s * o["x"] + c * o["y"]
        drift.append(math.hypot(mx - truth[j]["x"], my - truth[j]["y"]))
    # localisation estimates logged by the Jetson (k == "pose", e.g. src "slam"), against the truth nearest in time
    loc = {}
    for src in sorted({r.get("src") for r in win if r["k"] == "pose"}):
        errs, j = [], 0
        for r in (r for r in win if r["k"] == "pose" and r.get("src") == src):
            while j + 1 < len(truth) and truth[j + 1]["wall"] <= r["wall"]:
                j += 1
            errs.append(math.hypot(r["x"] - truth[j]["x"], r["y"] - truth[j]["y"]))
        ts = [r["wall"] for r in win if r["k"] == "pose" and r.get("src") == src]
        gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a > 1.0]   # the Jetson sends 5 per second: longer gaps = link stalls
        loc[src] = {"median": r2(statistics.median(errs)), "p95": r2(pct(errs, 0.95)), "max": r2(max(errs)), "end": r2(errs[-1]),
                    "samples": len(errs), "link_gaps_over_1s": len(gaps), "link_gap_max_s": r2(max(gaps) if gaps else 0.0)}
    # GNSS
    fixes = [g for g in gps if g.get("mode", 0) >= 2]
    buckets = {"open (<0.3)": [], "partial (0.3-0.6)": [], "dense (>=0.6)": []}
    avail = {k: [0, 0] for k in buckets}
    for g in gps:
        cv = g.get("cover", 0.0)
        k = "open (<0.3)" if cv < 0.3 else ("partial (0.3-0.6)" if cv < 0.6 else "dense (>=0.6)")
        avail[k][1] += 1
        if g.get("mode", 0) >= 2:
            avail[k][0] += 1
            buckets[k].append(g["err_m"])
    # faults through the side camera's view (it looks left, 100 degrees wide)
    faults = []
    for ft in meta["faults"]:
        seen_t, best = 0.0, 1e9
        for a, b in zip(truth, truth[1:]):
            dx, dy = ft["x"] - a["x"], ft["y"] - a["y"]
            cy, sy_ = math.cos(a["yaw"]), math.sin(a["yaw"])
            xr, yr = cy * dx + sy_ * dy, -sy_ * dx + cy * dy
            d = math.hypot(xr, yr)
            best = min(best, d)
            if yr > 0 and d < 6.0 and abs(math.degrees(math.atan2(xr, yr))) < 50:
                seen_t += b["wall"] - a["wall"]
        faults.append({"id": ft["id"], "type": ft["type"], "closest_m": r2(best), "in_view_s": r2(seen_t)})
    st = final if final and final.get("src") == "patrol" else {}
    return {
        "pose_topic": pose_topic, "result": st.get("state", "running"),
        "route": {"completion_pct": round(100 * done_m / cum[-1], 1), "along_route_m": round(done_m, 1),
                  "route_m": round(cum[-1], 1), "travelled_m": round(travelled, 1), "duration_s": round(dur, 1),
                  "mean_speed_ms": r2(travelled / dur if dur > 0 else 0.0),
                  "cross_track_m": {"median": r2(statistics.median(xte)), "p95": r2(pct(xte, 0.95)), "max": r2(max(xte))}},
        "localisation_error_m": loc,
        "odom_drift_m": {"end": r2(drift[-1] if drift else None), "max": r2(max(drift) if drift else None),
                         "per_100m": r2(100 * drift[-1] / travelled if drift and travelled > 1 else None)},
        "gnss": {"samples": len(gps), "fix_pct": round(100 * len(fixes) / len(gps), 1) if gps else None,
                 "fix_3d_pct": round(100 * sum(1 for g in gps if g.get("mode") == 3) / len(gps), 1) if gps else None,
                 "error_m": {"median": r2(statistics.median([g["err_m"] for g in fixes]) if fixes else None),
                             "p95": r2(pct([g["err_m"] for g in fixes], 0.95))},
                 "by_cover": {k: {"share_pct": round(100 * avail[k][1] / len(gps), 1) if gps else None,
                                  "fix_pct": round(100 * avail[k][0] / avail[k][1], 1) if avail[k][1] else None,
                                  "error_median_m": r2(statistics.median(v) if v else None), "error_p95_m": r2(pct(v, 0.95))}
                              for k, v in buckets.items()}},
        "faults_in_view": faults, "faults_seen": sum(1 for f in faults if f["in_view_s"] and f["in_view_s"] > 0.5),
        "obstacle_stops": st.get("obstacle_stops"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", nargs="?", help="run/ugv/<time> (default: the newest)")
    ap.add_argument("--json", action="store_true", help="write summary.json next to the log")
    a = ap.parse_args()
    run = a.run or max(glob.glob(os.path.join(ROOT, "run", "ugv", "*")), key=os.path.getmtime)
    with open(os.path.join(run, "log.jsonl")) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    with open(META) as f:
        meta = json.load(f)
    out = []
    for t0, t1, pose_topic, final in patrols(rows):
        sc = score(rows, meta, t0, t1, pose_topic, final)
        if sc:
            out.append(sc)
    print("run %s: %d patrol(s)" % (os.path.relpath(run, ROOT), len(out)))
    for i, sc in enumerate(out, 1):
        R, D, G = sc["route"], sc["odom_drift_m"], sc["gnss"]
        print("\n#%d  pose from %s -> %s" % (i, sc["pose_topic"], sc["result"]))
        print("  route      %5.1f%% of %.0f m in %.0f s (%.2f m/s); off the route: median %.2f m, p95 %.2f m, max %.2f m" % (
            R["completion_pct"], R["route_m"], R["duration_s"], R["mean_speed_ms"] or 0, R["cross_track_m"]["median"],
            R["cross_track_m"]["p95"], R["cross_track_m"]["max"]))
        print("  odometry   drift at the end %s m, max %s m, %s m per 100 m" % (D["end"], D["max"], D["per_100m"]))
        for src, e in sc["localisation_error_m"].items():
            print("  %-10s error median %s m, p95 %s m, max %s m, at the end %s m | link: %d gaps over 1 s, longest %s s" % (
                src, e["median"], e["p95"], e["max"], e["end"], e["link_gaps_over_1s"], e["link_gap_max_s"]))
        print("  GNSS       fix %s%% (3D %s%%), error median %s m, p95 %s m" % (G["fix_pct"], G["fix_3d_pct"], G["error_m"]["median"], G["error_m"]["p95"]))
        for k, v in G["by_cover"].items():
            print("             %-18s %5s%% of the time: fix %s%%, error median %s m, p95 %s m" % (k, v["share_pct"], v["fix_pct"], v["error_median_m"], v["error_p95_m"]))
        print("  faults     %d of %d through the camera's view: %s" % (sc["faults_seen"], len(sc["faults_in_view"]),
              ", ".join("%s %ss" % (f["id"], f["in_view_s"]) for f in sc["faults_in_view"])))
        print("  obstacles  %s stop(s)" % sc["obstacle_stops"])
    if a.json:
        with open(os.path.join(run, "summary.json"), "w") as f:
            json.dump({"run": os.path.basename(run), "patrols": out}, f, indent=1)
        print("\nwrote %s" % os.path.relpath(os.path.join(run, "summary.json"), ROOT))


if __name__ == "__main__":
    main()
