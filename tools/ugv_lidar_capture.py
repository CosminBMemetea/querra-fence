"""Listen to the running forest simulation for SECONDS and save every 2nd LiDAR scan as world-frame points.

  tools/ugv_lidar_view.sh runs it (Gazebo's Python, GZ_PARTITION=querra_ugv); by hand:
  python tools/ugv_lidar_capture.py OUT.npz SECONDS

Each scan is placed with the simulator's true pose at the scan's simulation time, so the cloud shows what the
LiDAR sees, not a SLAM result. It only listens: the relay and the patrol are not disturbed.
"""
import json, math, sys, time, threading, bisect
import numpy as np
from gz.transport13 import Node
from gz.msgs10.laserscan_pb2 import LaserScan
from gz.msgs10.odometry_pb2 import Odometry

out, secs = sys.argv[1], float(sys.argv[2])
meta = json.load(open("worlds/forest_meta.json"))
LX, LY, LZ = meta["robot"]["lidar"]["xyz"] if "robot" in meta and "lidar" in meta["robot"] else (0.12, 0.0, 0.52)
lock = threading.Lock()
truth_t, truth_p, scans = [], [], []
n_scan = [0]


def st(m):
    return m.header.stamp.sec + m.header.stamp.nsec * 1e-9


def on_truth(m):
    p, q = m.pose.position, m.pose.orientation
    with lock:
        truth_t.append(st(m)); truth_p.append((p.x, p.y, p.z, q.w, q.x, q.y, q.z))


def on_lidar(m):
    n_scan[0] += 1
    if n_scan[0] % 2:
        return
    r = np.asarray(m.ranges, dtype=np.float32)
    with lock:
        scans.append((st(m), m.count, m.vertical_count, m.angle_min, m.angle_step, m.vertical_angle_min,
                      m.vertical_angle_step, m.range_min, m.range_max, r))


node = Node()
node.subscribe(Odometry, meta["topics"]["ground_truth"], on_truth)
node.subscribe(LaserScan, meta["topics"]["lidar"], on_lidar)
time.sleep(secs)
with lock:
    tt, tp, sc = list(truth_t), list(truth_p), list(scans)
pts, poses, last = [], [], None
for (s, cnt, vc, a0, da, v0, dv, rmin, rmax, r) in sc:
    i = min(range(len(tt)), key=lambda k: abs(tt[k] - s)) if len(tt) < 50 else None
    if i is None:
        j = bisect.bisect_left(tt, s); i = min([k for k in (j - 1, j) if 0 <= k < len(tt)], key=lambda k: abs(tt[k] - s))
    if abs(tt[i] - s) > 0.06:
        continue
    x, y, z, qw, qx, qy, qz = tp[i]
    R = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                  [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                  [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    rr = r.reshape(vc, cnt)
    az = a0 + da * np.arange(cnt)[None, :]
    el = v0 + dv * np.arange(vc)[:, None]
    ok = np.isfinite(rr) & (rr > rmin) & (rr < rmax * 0.999)
    ce = np.cos(el)
    P = np.stack([rr * ce * np.cos(az), rr * ce * np.sin(az), rr * np.sin(el) * np.ones_like(az)], -1)[ok]
    P = P + np.array([LX, LY, LZ])
    W = P @ R.T + np.array([x, y, z])
    pts.append(W.astype(np.float32))
    poses.append((s, x, y, z, math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))))
    last = W.astype(np.float32)
np.savez_compressed(out, pts=np.concatenate(pts), poses=np.array(poses), last=last,
                    sizes=np.array([len(p) for p in pts]))
print("scans", len(pts), "points", sum(len(p) for p in pts), "path from", poses[0][1:3], "to", poses[-1][1:3])
