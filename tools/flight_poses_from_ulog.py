"""Measures how the drone really flies the inspection mission, from PX4 SITL logs, for make_dataset.py --style v4.

    python tools/flight_poses_from_ulog.py LOG.ulg [LOG.ulg ...] --out ml/flight_poses.json   (needs pyulog)

Keeps the AUTO_MISSION part above 10 m and samples it at about 12 Hz. For every sample it writes, relative to the
planned route of fence.json (geo.mission_path):
  offset_m          distance outside the fence (negative: inside)
  heading_dev_deg   heading minus the planned route's bearing
  cam_pitch_deg     55 minus the body pitch: the camera is fixed at 55 deg and the drone noses down when it flies
  roll_deg, alt_m, speed_ms
  corner_m          distance to the nearest fence corner
The logs must come from flights over the default fence.json. The local frame's origin is the drone pad.
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from pyulog import ULog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import geo  # noqa: E402

AUTO_MISSION = 3


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
    return math.hypot(p[0] - ax - t * (bx - ax), p[1] - ay - t * (by - ay))


def inside(p, poly):
    x, y, c = p[0], p[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", default=os.path.join(ROOT, "ml", "flight_poses.json"))
    ap.add_argument("--every", type=int, default=20, help="keep every Nth attitude sample (the log runs at ~250 Hz)")
    a = ap.parse_args()
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    poly, route = cfg["fence"]["polygon"], geo.mission_path(cfg, fence)
    bearing = [math.degrees(math.atan2(route[i + 1][0] - route[i][0], route[i + 1][1] - route[i][1])) for i in range(len(route) - 1)]
    rows = []
    for log in a.logs:
        u = ULog(log, ["vehicle_attitude", "vehicle_local_position", "vehicle_status"])
        att, lp, vs = (u.get_dataset(n).data for n in ("vehicle_attitude", "vehicle_local_position", "vehicle_status"))
        q0, q1, q2, q3 = (att["q[%d]" % i] for i in range(4))
        t = att["timestamp"]
        pitch = np.degrees(np.arcsin(np.clip(2 * (q0 * q2 - q3 * q1), -1, 1)))
        roll = np.degrees(np.arctan2(2 * (q0 * q1 + q2 * q3), 1 - 2 * (q1 ** 2 + q2 ** 2)))
        yaw = np.degrees(np.arctan2(2 * (q0 * q3 + q1 * q2), 1 - 2 * (q2 ** 2 + q3 ** 2)))
        nav = np.round(np.interp(t, vs["timestamp"], vs["nav_state"]))
        east, north, down = (np.interp(t, lp["timestamp"], lp[k]) for k in ("y", "x", "z"))
        ve, vn = (np.interp(t, lp["timestamp"], lp[k]) for k in ("vy", "vx"))
        for i in np.where((nav == AUTO_MISSION) & (-down > 10) & (np.hypot(ve, vn) > 1.0))[0][::a.every]:
            p = (float(east[i]), float(north[i]))
            d = min(seg_dist(p, poly[k], poly[(k + 1) % len(poly)]) for k in range(len(poly)))
            k = min(range(len(route) - 1), key=lambda j: seg_dist(p, route[j], route[j + 1]))
            rows.append(dict(offset_m=round(-d if inside(p, poly) else d, 2),
                             heading_dev_deg=round(float((yaw[i] - bearing[k] + 180) % 360 - 180), 1),
                             cam_pitch_deg=round(55 - float(pitch[i]), 1), roll_deg=round(float(roll[i]), 1),
                             alt_m=round(float(-down[i]), 2), speed_ms=round(float(np.hypot(ve[i], vn[i])), 2),
                             corner_m=round(min(math.hypot(p[0] - c[0], p[1] - c[1]) for c in poly), 1)))
    with open(a.out, "w") as f:
        json.dump({"source": "PX4 SITL logs of mission flights over fence.json (%s); AUTO_MISSION above 10 m, every %dth "
                             "attitude sample" % (", ".join(os.path.basename(x) for x in a.logs), a.every),
                   "tool": "tools/flight_poses_from_ulog.py",
                   "fields": "offset_m outside the fence; heading_dev_deg against the planned route; cam_pitch_deg = 55 - "
                             "body pitch; corner_m to the nearest fence corner",
                   "samples": rows}, f)
    near = sum(r["corner_m"] < 12 for r in rows)
    print("%d samples, %d%% within 12 m of a corner -> %s" % (len(rows), round(100 * near / len(rows)), a.out))


if __name__ == "__main__":
    main()
