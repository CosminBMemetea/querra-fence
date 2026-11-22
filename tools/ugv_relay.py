"""Ground robot relay: the Gazebo robot on the Mac <-> the Jetson's ROS 2 (querra_fence_ros ugv_bridge), one TCP link.

The Mac plays the robot's body and sensors, the Jetson is its brain. This relay serves the robot's sensors on a TCP
port and drives the robot with the velocity commands that come back:

  Mac -> Jetson, one framed message per sample (every header carries "st", Gazebo's simulation time of the sample):
      b"QUG1" | kind (1 byte) | uint32 BE header_len | uint32 BE payload_len | header JSON | payload
      M  meta, once per connection: worlds/forest_meta.json (route, spawn, sensor mounts, faults, crowns dropped)
      L  LiDAR scan: header {t, count, vcount, angle_min, angle_step, vangle_min, vangle_step}, payload float16 ranges
         (vertical-major: all horizontal samples of the lowest beam first)
      C  camera: header {t, w, h}, payload JPEG (ffmpeg, the same encoder as tools/cam_stream.py)
      I  IMU at 50 Hz: {t, q: [x, y, z, w], w: [x, y, z], a: [x, y, z]}
      O  wheel odometry: {t, x, y, yaw, v, w} in the odom frame (starts at 0, 0, 0), with the error model of
         forest.json "odom" (Gazebo's own skid-steer odometry is near perfect)
      G  GNSS at forest.json "gps" rate_hz: {t, lat, lon, alt, mode, eph, cover, sats}, degraded under the crowns
      T  ground truth: {t, x, y, z, yaw} in the world frame (for scoring and for Foxglove only, never for driving)
  Jetson -> Mac, one JSON object per line:
      {"cmd_vel": [v, w]}   m/s, rad/s; the robot stops if no command arrives for 0.5 s
      {"reset": true}       put the robot back at the spawn pose and zero the odometry (for repeated patrols)
      {"event": {...}}      logged as is (the patrol's state changes)
      {"pose": {"src", "x", "y", "yaw"}}   a localisation estimate in the world frame (the SLAM pose), logged for scoring

Each client gets the newest LiDAR scan and camera frame (stale ones are dropped); IMU, odometry, GNSS and truth are
queued. Everything the patrol needs for scoring is logged to run/ugv/<time>/log.jsonl (truth, odometry, GNSS,
commands, resets).

Run with tools/ugv_relay.sh (sets up the Gazebo environment), on ./ugv.sh's simulation.
"""
import argparse
import collections
import json
import math
import os
import random
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

import numpy as np
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image
from gz.msgs10.imu_pb2 import IMU
from gz.msgs10.laserscan_pb2 import LaserScan
from gz.msgs10.odometry_pb2 import Odometry
from gz.msgs10.twist_pb2 import Twist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import cam_stream  # noqa: E402  (Encoder)
import geo  # noqa: E402

META = os.path.join(ROOT, "worlds", "forest_meta.json")
MAGIC = b"QUG1"
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def sim_t(m):
    """Gazebo's simulation time of a message: every sample carries it as "st", so the Jetson can stamp them all on one
    clock (/clock). Stamping on arrival mixes each stream's own delay into the stamps, and SLAM then matches a scan
    against the wrong odometry pose during a turn."""
    return round(m.header.stamp.sec + m.header.stamp.nsec * 1e-9, 4)


def frame(kind, header, payload=b""):
    h = json.dumps(header, separators=(",", ":")).encode()
    return MAGIC + kind.encode() + struct.pack(">II", len(h), len(payload)) + h + payload


class Canopy:
    """Sky cover at a point (0 open sky .. 1 nothing visible) from the tree crowns in the meta file.

    Each crown within reach_m hides the cap of sky it subtends, seen from the antenna (0.8 m up), if it rises above
    the 15 degree elevation mask under which a receiver ignores satellites anyway; leaves attenuate the signal rather
    than stop it, so a crown hides only foliage_block of its cap. Caps combine as independent obstacles.
    """
    MASK_SKY = 1.0 - math.sin(math.radians(15))      # share of the hemisphere above the elevation mask

    def __init__(self, crowns, foliage_block=0.6, reach_m=20.0, cell=8.0):
        self.cell, self.reach, self.k, self.g = cell, reach_m, foliage_block, collections.defaultdict(list)
        for c in crowns:
            x, y, r = c[:3]
            h = c[3] if len(c) > 3 else 6.0
            self.g[(int(x // cell), int(y // cell))].append((x, y, r, h))

    def cover(self, x, y, antenna_z=0.8):
        cx, cy = int(x // self.cell), int(y // self.cell)
        n = int(math.ceil(self.reach / self.cell))
        visible = 1.0
        for i in range(cx - n, cx + n + 1):
            for j in range(cy - n, cy + n + 1):
                for (tx, ty, r, h) in self.g.get((i, j), ()):
                    d = math.hypot(tx - x, ty - y)
                    if d > self.reach:
                        continue
                    dz = max(h - antenna_z, 0.1)
                    top_elev = math.atan2(dz + r * 0.7, max(d - r, 0.0))
                    if top_elev < math.radians(15):
                        continue
                    alpha = math.atan2(r, math.hypot(d, dz))        # angular radius of the crown
                    cap = min(1.0, (1.0 - math.cos(alpha)) / self.MASK_SKY)
                    visible *= 1.0 - self.k * cap
        return 1.0 - visible


class Gnss:
    """GNSS under canopy: white noise and a Gauss-Markov multipath bias, both growing with sky cover."""
    def __init__(self, meta, seed=5):
        self.cfg, self.cfg_geo = meta["gps"], {"origin": meta["origin"]}
        self.canopy = Canopy(meta["crowns"], meta["gps"].get("foliage_block", 0.6))
        self.rnd = random.Random(seed)
        self.bias = [0.0, 0.0]
        self.t_last = None

    def reset(self):
        self.bias, self.t_last = [0.0, 0.0], None

    def sample(self, t, x, y, z):
        c = self.cfg
        cover = self.canopy.cover(x, y)
        dt = 0.2 if self.t_last is None else min(max(t - self.t_last, 1e-3), 2.0)
        self.t_last = t
        sb = cover * c["canopy_bias_m"]
        tau = c["bias_tau_s"]
        for k in range(2):
            self.bias[k] += -self.bias[k] * dt / tau + math.sqrt(2 * dt / tau) * sb * self.rnd.gauss(0, 1)
        sigma = c["open_sigma_m"] + cover * (c["canopy_sigma_m"] - c["open_sigma_m"])
        mode = 3 if cover < 0.6 else (2 if cover < c["no_fix_cover"] else 1)
        out = {"t": round(t, 3), "cover": round(cover, 3), "mode": mode, "sats": max(3, 12 - round(cover * 9))}
        if mode >= 2:
            ex = self.bias[0] + self.rnd.gauss(0, sigma)
            ey = self.bias[1] + self.rnd.gauss(0, sigma)
            lat, lon = geo.enu_to_gps(self.cfg_geo, x + ex, y + ey)
            # a receiver under trees underestimates its own error (it cannot see the multipath)
            out.update(lat=round(lat, 8), lon=round(lon, 8), alt=round(self.cfg_geo["origin"]["alt_m"] + z, 2),
                       eph=round(0.7 * math.hypot(sigma, sb), 2), err_m=round(math.hypot(ex, ey), 2))
        return out


class WheelOdom:
    """Integrates Gazebo's odometry increments with forest.json "odom" errors (scale, turn scale, heading drift per metre)."""
    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.rnd = random.Random(self.cfg.get("seed", 3))
        self.reset()

    def reset(self):
        c = self.cfg
        # fixed per run, like a mis-calibrated wheel radius and track
        self.k_s = 1.0 + self.rnd.choice((-1, 1)) * c.get("scale_err", 0.0)
        self.k_y = 1.0 + self.rnd.choice((-1, 1)) * c.get("yaw_scale_err", 0.0)
        self.drift = self.rnd.choice((-1, 1)) * math.radians(c.get("yaw_drift_deg_per_100m", 0.0)) / 100.0   # rad per m
        self.prev = None
        self.x = self.y = self.yaw = 0.0

    def update(self, t, gx, gy, gyaw, v, w):
        if self.prev is None:
            self.prev = (t, gx, gy, gyaw)
            return None
        t0, x0, y0, yaw0 = self.prev
        self.prev = (t, gx, gy, gyaw)
        ds = (gx - x0) * math.cos(yaw0) + (gy - y0) * math.sin(yaw0)
        dyaw = wrap(gyaw - yaw0) * self.k_y + self.drift * abs(ds)    # no drift while the wheels stand still
        ds *= self.k_s
        mid = self.yaw + dyaw / 2
        self.x += ds * math.cos(mid)
        self.y += ds * math.sin(mid)
        self.yaw = wrap(self.yaw + dyaw)
        return {"t": round(t, 3), "x": round(self.x, 4), "y": round(self.y, 4), "yaw": round(self.yaw, 5),
                "v": round(v * self.k_s, 4), "w": round(w * self.k_y + self.drift * abs(v), 5)}


class Client:
    def __init__(self, conn, addr):
        self.conn, self.addr = conn, addr
        self.latest = {}                         # kind -> frame bytes (L, C: newest only)
        self.queue = collections.deque(maxlen=600)
        self.cv = threading.Condition()
        self.alive = True

    def put(self, kind, data):
        with self.cv:
            if kind in "LC":
                self.latest[kind] = data
            else:
                self.queue.append(data)
            self.cv.notify()


class Relay:
    def __init__(self, args):
        with open(META) as f:
            self.meta = json.load(f)
        self.args = args
        self.node = Node()
        self.clients, self.lock = [], threading.Lock()
        self.gnss = Gnss(self.meta)
        self.odom = WheelOdom(self.meta.get("odom"))
        self.truth = None
        self.cmd, self.cmd_t = (0.0, 0.0), 0.0
        self.counts = collections.Counter()
        self.t_imu = self.t_gps = self.t_log_truth = self.t_log_odom = 0.0
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.logdir = os.path.join(ROOT, "run", "ugv", stamp)
        os.makedirs(self.logdir, exist_ok=True)
        self.log_f = open(os.path.join(self.logdir, "log.jsonl"), "a", buffering=1)
        self.log({"k": "start", "world": self.meta["world"], "route_length_m": self.meta["route_length_m"],
                  "spawn": self.meta["spawn"], "faults": self.meta["faults"], "odom_model": self.meta.get("odom"),
                  "gps_model": self.meta["gps"]})
        ffmpeg = os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin", "ffmpeg")
        self.encoder = cam_stream.Encoder(ffmpeg if os.path.exists(ffmpeg) else (shutil.which("ffmpeg") or "ffmpeg"),
                                          args.quality, self.on_jpeg)
        self.cam_busy = False
        self.reset_lock = threading.Lock()
        self.cmd_pub = self.node.advertise(self.meta["topics"]["cmd_vel"], Twist)
        T = self.meta["topics"]
        self.node.subscribe(LaserScan, T["lidar"], self.on_lidar)
        self.node.subscribe(Image, T["camera"], self.on_camera)
        self.node.subscribe(IMU, T["imu"], self.on_imu)
        self.node.subscribe(Odometry, T["odom"], self.on_odom)
        self.node.subscribe(Odometry, T["ground_truth"], self.on_truth)

    def log(self, row):
        row.setdefault("wall", round(time.time(), 3))
        try:
            self.log_f.write(json.dumps(row, separators=(",", ":")) + "\n")
        except ValueError:
            pass

    def broadcast(self, kind, data):
        self.counts[kind] += 1
        with self.lock:
            clients = list(self.clients)
        for c in clients:
            c.put(kind, data)

    # ---- Gazebo -> clients
    def on_lidar(self, m):
        r = np.asarray(m.ranges, dtype=np.float32).astype(np.float16).tobytes()
        h = {"t": round(time.time(), 3), "st": sim_t(m), "count": m.count, "vcount": m.vertical_count, "angle_min": m.angle_min,
             "angle_step": m.angle_step, "vangle_min": m.vertical_angle_min, "vangle_step": m.vertical_angle_step,
             "range_min": m.range_min, "range_max": m.range_max}
        self.broadcast("L", frame("L", h, r))

    def on_camera(self, m):
        if self.cam_busy and len(self.encoder.pending) > 2:     # encoder behind: drop this frame
            return
        self.cam_busy = True
        self.encoder.push({"t": round(time.time(), 3), "st": sim_t(m), "w": m.width, "h": m.height, "t_gz_recv": time.time()},
                          m.data, m.width, m.height)

    def on_jpeg(self, header, jpeg):
        header.pop("t_gz_recv", None)
        self.broadcast("C", frame("C", header, jpeg))

    def on_imu(self, m):
        now = time.time()
        if now - self.t_imu < 0.019:
            return
        self.t_imu = now
        q, w, a = m.orientation, m.angular_velocity, m.linear_acceleration
        self.broadcast("I", frame("I", {"t": round(now, 4), "st": sim_t(m), "q": [q.x, q.y, q.z, q.w], "w": [w.x, w.y, w.z],
                                        "a": [a.x, a.y, a.z]}))

    def on_odom(self, m):
        now = time.time()
        o = self.odom.update(now, m.pose.position.x, m.pose.position.y, yaw_of(m.pose.orientation),
                             m.twist.linear.x, m.twist.angular.z)
        if o is None:
            return
        o["st"] = sim_t(m)
        self.broadcast("O", frame("O", o))
        if now - self.t_log_odom >= 0.2:
            self.t_log_odom = now
            self.log(dict(o, k="odom"))

    def on_truth(self, m):
        now = time.time()
        p = m.pose.position
        tr = {"t": round(now, 3), "st": sim_t(m), "x": round(p.x, 3), "y": round(p.y, 3), "z": round(p.z, 3), "yaw": round(yaw_of(m.pose.orientation), 4)}
        self.truth = tr
        self.broadcast("T", frame("T", tr))
        if now - self.t_log_truth >= 0.2:
            self.t_log_truth = now
            self.log(dict(tr, k="truth"))
        if now - self.t_gps >= 1.0 / self.meta["gps"]["rate_hz"]:
            self.t_gps = now
            g = self.gnss.sample(now, p.x, p.y, p.z)
            g["st"] = tr["st"]
            self.log(dict(g, k="gps"))
            g.pop("err_m", None)                  # the robot never knows its true GNSS error
            self.broadcast("G", frame("G", g))

    # ---- clients -> Gazebo
    def drive_loop(self):
        t = Twist()
        last_log = 0.0
        while running:
            v, w = self.cmd if time.time() - self.cmd_t < 0.5 else (0.0, 0.0)
            t.linear.x, t.angular.z = v, w
            self.cmd_pub.publish(t)
            if time.time() - last_log >= 0.5 and (v or w):
                last_log = time.time()
                self.log({"k": "cmd", "v": round(v, 3), "w": round(w, 3)})
            time.sleep(0.05)

    def reset(self):
        """Back to the spawn pose. Through the gz CLI: a Node.request() from this process can wait out its timeout,
        because the reply has to pass the transport thread that is busy delivering the sensor callbacks."""
        if not self.reset_lock.acquire(blocking=False):  # one reset at a time (a command can arrive twice)
            return
        try:
            x, y, yaw = self.meta["spawn"]
            self.cmd, self.cmd_t = (0.0, 0.0), 0.0
            req = 'name: "querra_ugv", position: {x: %.3f, y: %.3f, z: 0.05}, orientation: {z: %.5f, w: %.5f}' % (
                x, y, math.sin(yaw / 2), math.cos(yaw / 2))
            try:
                out = subprocess.run(["gz", "service", "-s", "/world/%s/set_pose" % self.meta["world"], "--reqtype", "gz.msgs.Pose",
                                      "--reptype", "gz.msgs.Boolean", "--timeout", "5000", "--req", req],
                                     capture_output=True, text=True, timeout=15)
                ok = "data: true" in out.stdout
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            time.sleep(0.6)
            self._finish_reset(ok)
        finally:
            self.reset_lock.release()

    def _finish_reset(self, ok):
        self.odom.reset()
        self.gnss.reset()
        self.log({"k": "reset", "ok": bool(ok)})
        print("[ugv_relay] reset to spawn: %s" % ("ok" if ok else "FAILED"), flush=True)

    def serve(self, c):
        meta = {k: v for k, v in self.meta.items() if k != "crowns"}
        c.put("M", frame("M", meta))
        threading.Thread(target=self.reader, args=(c,), daemon=True).start()
        sent = 0
        try:
            while running and c.alive:
                with c.cv:
                    if not c.queue and not c.latest:
                        c.cv.wait(0.5)
                    out = list(c.queue)
                    c.queue.clear()
                    out += list(c.latest.values())
                    c.latest.clear()
                for data in out:
                    c.conn.sendall(data)
                    sent += 1
        except OSError:
            pass
        finally:
            c.alive = False
            with self.lock:
                if c in self.clients:
                    self.clients.remove(c)
            c.conn.close()
            self.log({"k": "client_gone", "addr": c.addr[0], "sent": sent})
            print("[ugv_relay] client %s gone after %d messages" % (c.addr[0], sent), flush=True)

    def reader(self, c):
        f = c.conn.makefile("r", encoding="utf-8", errors="replace")
        try:
            for line in f:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if "cmd_vel" in m:
                    v, w = (float(m["cmd_vel"][0]), float(m["cmd_vel"][1]))
                    self.cmd, self.cmd_t = (max(-0.6, min(1.2, v)), max(-1.2, min(1.2, w))), time.time()
                if m.get("reset"):
                    threading.Thread(target=self.reset, daemon=True).start()
                if "event" in m:
                    self.log({"k": "event", **m["event"]})
                if "pose" in m:                       # a localisation estimate from the Jetson (e.g. SLAM), for scoring
                    self.log({"k": "pose", **m["pose"]})
        except (OSError, ValueError):
            pass
        c.alive = False

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.args.bind, self.args.port))
        srv.listen(4)
        srv.settimeout(0.5)
        threading.Thread(target=self.drive_loop, daemon=True).start()
        print("[ugv_relay] serving the robot on tcp://%s:%d, log %s" % (self.args.bind, self.args.port,
                                                                       os.path.relpath(self.logdir, ROOT)), flush=True)
        t_stat = time.time()
        while running:
            try:
                conn, addr = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                c = Client(conn, addr)
                with self.lock:
                    self.clients.append(c)
                self.log({"k": "client", "addr": addr[0]})
                print("[ugv_relay] client %s connected" % addr[0], flush=True)
                threading.Thread(target=self.serve, args=(c,), daemon=True).start()
            except socket.timeout:
                pass
            if time.time() - t_stat >= 10:
                dt = time.time() - t_stat
                t_stat = time.time()
                rates = " ".join("%s %.1f/s" % (k, n / dt) for k, n in sorted(self.counts.items()))
                self.counts.clear()
                with self.lock:
                    nc = len(self.clients)
                print("[ugv_relay] %d client(s) | %s" % (nc, rates), flush=True)
        srv.close()
        self.encoder.close()
        self.log({"k": "stop"})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5611)
    ap.add_argument("--quality", type=int, default=4, help="camera JPEG, ffmpeg -q:v (4 = the drone stream's)")
    Relay(ap.parse_args()).run()


if __name__ == "__main__":
    main()
