"""Regizorul simulării (rulează cu Python-ul din mediul Gazebo, are gz.transport13):

* plimbă animalele (pasc, merg; cele evadate rămân afară, lângă spărtura din gard)
* scrie pozițiile live în run/animals_live.json (le citește detectorul din mission.py)
* camera GUI urmărește lin drona
* desenează traseul planificat și marcaje 3D pentru fiecare detecție (run/events.jsonl)
"""
import json
import math
import os
import random
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402

from gz.transport13 import Node  # noqa: E402
from gz.msgs10.boolean_pb2 import Boolean  # noqa: E402
from gz.msgs10.cameratrack_pb2 import CameraTrack  # noqa: E402
from gz.msgs10.empty_pb2 import Empty  # noqa: E402
from gz.msgs10.marker_pb2 import Marker  # noqa: E402
from gz.msgs10.pose_pb2 import Pose  # noqa: E402
from gz.msgs10.pose_v_pb2 import Pose_V  # noqa: E402

WORLD = os.environ.get("GARDIAN_WORLD", "pasture")
DRONE = os.environ.get("GARDIAN_DRONE", "x500_fence")
RATE_HZ = 20.0
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


class Animal:
    def __init__(self, a, poly, rnd):
        self.__dict__.update(a)
        self.poly = poly
        self.rnd = rnd
        self.mode = "graze"
        self.timer = rnd.uniform(1, 12)
        self.tx, self.ty = self.x, self.y
        self.speed = 0.0
        self.max_speed = rnd.uniform(0.7, 1.0) if self.kind == "cow" else rnd.uniform(0.55, 0.85)
        self.phase = rnd.uniform(0, 6.28)
        self.home = a.get("home", (self.x, self.y))

    def ok(self, x, y):
        d = geo.dist_to_polyline(self.poly, x, y)[0]
        if self.escaped:
            return (not geo.inside(self.poly, x, y)) and d > 3 and math.hypot(x - self.home[0], y - self.home[1]) < 20
        return geo.inside(self.poly, x, y) and d > 4.5

    def pick(self):
        for _ in range(60):
            r = self.rnd.uniform(4, 22)
            a = self.rnd.uniform(-math.pi, math.pi)
            x, y = self.x + math.cos(a) * r, self.y + math.sin(a) * r
            if self.ok(x, y):
                self.tx, self.ty = x, y
                return True
        return False

    def step(self, dt):
        self.timer -= dt
        if self.mode == "graze":
            self.speed = max(0.0, self.speed - dt * 0.8)
            if self.timer <= 0:
                if self.pick():
                    self.mode = "walk"
                self.timer = self.rnd.uniform(4, 14)
        else:
            dx, dy = self.tx - self.x, self.ty - self.y
            dist = math.hypot(dx, dy)
            want = math.atan2(dy, dx)
            err = (want - self.yaw + math.pi) % (2 * math.pi) - math.pi
            self.yaw += max(-0.9 * dt, min(0.9 * dt, err))
            target_speed = self.max_speed * max(0.0, math.cos(err)) * min(1.0, dist / 2.0)
            self.speed += max(-0.6 * dt, min(0.6 * dt, target_speed - self.speed))
            nx = self.x + math.cos(self.yaw) * self.speed * dt
            ny = self.y + math.sin(self.yaw) * self.speed * dt
            if self.ok(nx, ny) or not self.ok(self.x, self.y):
                self.x, self.y = nx, ny
            else:
                self.timer = 0
            if dist < 0.6 or self.timer <= 0:
                self.mode = "graze"
                self.timer = self.rnd.uniform(5, 18)
        self.phase += dt * self.speed * 6

    def pose(self):
        p = Pose()
        p.name = self.id
        p.position.x, p.position.y = self.x, self.y
        p.position.z = abs(math.sin(self.phase)) * 0.025 * min(1.0, self.speed)
        p.orientation.w = math.cos(self.yaw / 2)
        p.orientation.z = math.sin(self.yaw / 2)
        return p


def marker(ns, mid, mtype, pose, scale, rgba, points=None, lifetime=0):
    m = Marker()
    m.ns = ns
    m.id = mid
    m.action = Marker.ADD_MODIFY
    m.type = mtype
    m.pose.position.x, m.pose.position.y, m.pose.position.z = pose
    m.pose.orientation.w = 1.0
    m.scale.x, m.scale.y, m.scale.z = scale
    for attr in ("ambient", "diffuse", "emissive"):
        c = getattr(m.material, attr)
        c.r, c.g, c.b, c.a = rgba
    for (x, y, z) in points or []:
        pt = m.point.add()
        pt.x, pt.y, pt.z = x, y, z
    return m


def main():
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    rnd = random.Random(cfg.get("seed", 1) + 99)
    animals = [Animal(a, fence.poly, rnd) for a in geo.herd_layout(cfg, fence)]
    node = Node()
    os.makedirs(geo.RUN_DIR, exist_ok=True)
    live_path = os.path.join(geo.RUN_DIR, "animals_live.json")
    events_path = os.path.join(geo.RUN_DIR, "events.jsonl")

    svc_vec = "/world/%s/set_pose_vector" % WORLD
    svc_one = "/world/%s/set_pose" % WORLD
    use_vec = True

    track_pub = node.advertise("/gui/track", CameraTrack)
    alt = cfg["mission"]["altitude_m"]
    path = geo.mission_path(cfg, fence)
    path_drawn = False
    marked = 0
    # evenimentele vechi (zborul trecut) nu se mai desenează
    events_pos = os.path.getsize(events_path) if os.path.exists(events_path) else 0
    last_live = 0.0
    last_gui = 0.0
    t0 = time.time()
    dt = 1.0 / RATE_HZ
    next_t = time.time()
    print("[director] animale: %d (evadate: %d), lume: %s" % (len(animals), sum(a.escaped for a in animals), WORLD), flush=True)

    while running:
        now = time.time()
        for a in animals:
            a.step(dt)
        if use_vec:
            req = Pose_V()
            for a in animals:
                req.pose.append(a.pose())
            ok, _ = node.request(svc_vec, req, Pose_V, Boolean, 200)
            if not ok and now - t0 > 8:
                use_vec = False
                print("[director] set_pose_vector indisponibil, folosesc set_pose", flush=True)
        else:
            for a in animals:
                node.request(svc_one, a.pose(), Pose, Boolean, 100)

        if now - last_live > 0.5:
            last_live = now
            tmp = live_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"t": now, "animals": [dict(id=a.id, kind=a.kind, x=round(a.x, 2), y=round(a.y, 2)) for a in animals]}, f)
            os.replace(tmp, live_path)

        # GUI: camera lină după dronă + traseul planificat (repetăm până apare GUI-ul)
        if now - last_gui > 3.0 and now - t0 < 90:
            last_gui = now
            if os.environ.get("GARDIAN_DEMO"):
                # în modul demo camera e condusă de tools/capture_demo.py
                if not path_drawn:
                    pts = [(x, y, alt) for (x, y) in path]
                    ok, _ = node.request("/marker", marker("traseu", 1, Marker.LINE_STRIP, (0, 0, 0), (1, 1, 1), (1.0, 0.8, 0.1, 0.9), pts), Marker, Empty, 500)
                    path_drawn = ok
                continue_gui = False
            else:
                continue_gui = True
        else:
            continue_gui = False
        if continue_gui:
            ct = CameraTrack()
            ct.track_mode = CameraTrack.FOLLOW_LOOK_AT
            ct.follow_target.name = DRONE
            ct.track_target.name = DRONE
            ct.follow_offset.x, ct.follow_offset.y, ct.follow_offset.z = -10.0, -6.0, 5.5
            ct.follow_pgain = 0.04
            ct.track_pgain = 0.06
            track_pub.publish(ct)
            if not path_drawn:
                pts = [(x, y, alt) for (x, y) in path]
                ok, _ = node.request("/marker", marker("traseu", 1, Marker.LINE_STRIP, (0, 0, 0), (1, 1, 1), (1.0, 0.8, 0.1, 0.9), pts), Marker, Empty, 500)
                path_drawn = ok

        # marcaje pentru detecții noi; un zbor nou golește fișierul -> ștergem marcajele vechi
        if os.path.exists(events_path) and os.path.getsize(events_path) < events_pos:
            clear = Marker()
            clear.ns = "detectii"
            clear.action = Marker.DELETE_ALL
            node.request("/marker", clear, Marker, Empty, 300)
            events_pos = 0
        if os.path.exists(events_path):
            with open(events_path, encoding="utf-8") as f:
                f.seek(events_pos)
                for line in f:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    marked += 1
                    x, y = ev["x"], ev["y"]
                    if ev["kind"] == "fault":
                        col = (1.0, 0.55, 0.1, 0.55)
                        node.request("/marker", marker("detectii", marked * 2, Marker.CYLINDER, (x, y, 15), (0.5, 0.5, 30), col), Marker, Empty, 300)
                        node.request("/marker", marker("detectii", marked * 2 + 1, Marker.SPHERE, (x, y, 30.5), (1.6, 1.6, 1.6), (1.0, 0.6, 0.1, 0.9)), Marker, Empty, 300)
                    else:
                        col = (1.0, 0.2, 0.2, 0.5)
                        node.request("/marker", marker("detectii", marked * 2, Marker.CYLINDER, (x, y, 8), (0.3, 0.3, 16), col), Marker, Empty, 300)
                        node.request("/marker", marker("detectii", marked * 2 + 1, Marker.SPHERE, (x, y, 16.4), (1.0, 1.0, 1.0), (1.0, 0.25, 0.2, 0.9)), Marker, Empty, 300)
                events_pos = f.tell()

        next_t += dt
        sleep = next_t - time.time()
        if sleep > 0:
            time.sleep(sleep)
        else:
            next_t = time.time()
    print("[director] oprit", flush=True)


if __name__ == "__main__":
    main()
