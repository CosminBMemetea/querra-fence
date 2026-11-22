"""Sweep the ground robot along its route in the running forest simulation and keep one LiDAR scan at each stop.

  python tools/ugv_lidar_sweep.py OUT.npz [--step 1.5] [--near-faults 0.3]

Places the robot (set_pose, the way tools/ugv_relay.py resets it) every --step metres along the route, and every
--near-faults metres within 8 m of each fault, waits for a scan taken after it settled, and stores that scan in the
world frame with the simulator's true pose. No ROS and no Jetson: only Gazebo has to run (./ugv.sh). The result has
the same layout as tools/ugv_lidar_capture.py (pts, poses, sizes), plus the route position of each scan ("s").
tools/ugv_lidar_view.sh --sweep runs it and renders the views.
"""
import argparse
import bisect
import json
import math
import subprocess
import threading
import time

import numpy as np
from gz.transport13 import Node
from gz.msgs10.laserscan_pb2 import LaserScan
from gz.msgs10.odometry_pb2 import Odometry

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--step", type=float, default=1.5)
ap.add_argument("--near-faults", type=float, default=0.3)
a = ap.parse_args()
meta = json.load(open("worlds/forest_meta.json"))
LX, LY, LZ = (meta.get("robot", {}).get("lidar", {}) or {}).get("xyz", (0.12, 0.0, 0.52))
lock = threading.Lock()
truth_t, truth_p, scans = [], [], []


def st(m):
    return m.header.stamp.sec + m.header.stamp.nsec * 1e-9


def on_truth(m):
    p, q = m.pose.position, m.pose.orientation
    with lock:
        truth_t.append(st(m)); truth_p.append((p.x, p.y, p.z, q.w, q.x, q.y, q.z))
        if len(truth_t) > 4000:
            del truth_t[:2000]; del truth_p[:2000]


def on_lidar(m):
    with lock:
        scans.append((st(m), m))
        if len(scans) > 20:
            del scans[:10]


def place(x, y, yaw):
    req = 'name: "querra_ugv", position: {x: %.3f, y: %.3f, z: 0.05}, orientation: {z: %.5f, w: %.5f}' % (
        x, y, math.sin(yaw / 2), math.cos(yaw / 2))
    out = subprocess.run(["gz", "service", "-s", "/world/%s/set_pose" % meta["world"], "--reqtype", "gz.msgs.Pose",
                          "--reptype", "gz.msgs.Boolean", "--timeout", "5000", "--req", req],
                         capture_output=True, text=True, timeout=15)
    return "data: true" in out.stdout


def to_world(m, pose):
    x, y, z, qw, qx, qy, qz = pose
    R = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                  [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                  [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    rr = np.asarray(m.ranges, dtype=np.float32).reshape(m.vertical_count, m.count)
    az = m.angle_min + m.angle_step * np.arange(m.count)[None, :]
    el = m.vertical_angle_min + m.vertical_angle_step * np.arange(m.vertical_count)[:, None]
    ok = np.isfinite(rr) & (rr > m.range_min) & (rr < m.range_max * 0.999)
    ce = np.cos(el)
    P = np.stack([rr * ce * np.cos(az), rr * ce * np.sin(az), rr * np.sin(el) * np.ones_like(az)], -1)[ok]
    return ((P + np.array([LX, LY, LZ])) @ R.T + np.array([x, y, z])).astype(np.float32)


# the stops: every --step m along the route, and every --near-faults m within 8 m (along the route) of a fault
route = np.array(meta["route"], float)
cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(route, axis=0).T))])
stops = list(np.arange(0.0, cum[-1], a.step))
for f in meta["faults"]:
    stops += list(np.arange(max(0.0, f["s"] - 8.0), min(cum[-1], f["s"] + 8.0), a.near_faults))
stops = sorted(set(round(s, 2) for s in stops))

node = Node()
node.subscribe(Odometry, meta["topics"]["ground_truth"], on_truth)
node.subscribe(LaserScan, meta["topics"]["lidar"], on_lidar)
time.sleep(1.0)
pts, poses, sizes, kept, t0 = [], [], [], 0, time.time()
for n, s in enumerate(stops):
    i = min(int(np.searchsorted(cum, s)), len(route) - 2)
    x, y = np.interp(s, cum, route[:, 0]), np.interp(s, cum, route[:, 1])
    yaw = math.atan2(route[i + 1, 1] - route[i, 1], route[i + 1, 0] - route[i, 0])
    if not place(x, y, yaw):
        continue
    with lock:
        t_set = truth_t[-1] if truth_t else 0.0
    got, end = None, time.time() + 3.0
    while time.time() < end:                     # the second scan stamped 0.15 s (sim time) after the move
        with lock:
            later = [(t, m) for t, m in scans if t > t_set + 0.15]
        if len(later) >= 2:
            got = later[1]
            break
        time.sleep(0.02)
    if got is None:
        continue
    with lock:
        j = bisect.bisect_left(truth_t, got[0])
        cand = [k for k in (j - 1, j) if 0 <= k < len(truth_t)]
        k = min(cand, key=lambda k: abs(truth_t[k] - got[0])) if cand else None
        pose = truth_p[k] if k is not None else None
    if pose is None or math.hypot(pose[0] - x, pose[1] - y) > 0.3:
        continue
    W = to_world(got[1], pose)
    pts.append(W); sizes.append(len(W))
    qw, qx, qy, qz = pose[3:]
    poses.append((got[0], pose[0], pose[1], pose[2], math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)), s))
    kept += 1
    if n % 100 == 0:
        print("%d of %d stops, %d scans kept, %.0f s" % (n, len(stops), kept, time.time() - t0), flush=True)
np.savez_compressed(a.out, pts=np.concatenate(pts), poses=np.array(poses)[:, :5], s=np.array(poses)[:, 5],
                    sizes=np.array(sizes), last=pts[-1])
print("scans %d of %d stops, points %d, %.0f s" % (kept, len(stops), sum(sizes), time.time() - t0))
