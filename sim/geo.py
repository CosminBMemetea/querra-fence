"""Pasture geometry: fence, posts, faults, drone route, GPS conversions.

Standard library only, so it runs with both the PX4 .venv Python (pymavlink)
and the Gazebo (pixi) Python.
Local coordinates: x = east, y = north (ENU), in metres; origin = the drone pad.
"""
import json
import math
import os
import random

import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.path.join(ROOT, "run")


def load_config(path=None):
    with open(path or os.path.join(ROOT, "fence.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------- GPS <-> local ----------
def _m_per_deg(lat0):
    p = math.radians(lat0)
    m_lat = 111132.954 - 559.822 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
    m_lon = 111412.84 * math.cos(p) - 93.5 * math.cos(3 * p)
    return m_lat, m_lon


def enu_to_gps(cfg, x, y):
    o = cfg["origin"]
    m_lat, m_lon = _m_per_deg(o["lat"])
    return o["lat"] + y / m_lat, o["lon"] + x / m_lon


def gps_to_enu(cfg, lat, lon):
    o = cfg["origin"]
    m_lat, m_lon = _m_per_deg(o["lat"])
    return (lon - o["lon"]) * m_lon, (lat - o["lat"]) * m_lat


# ---------- polygon helpers ----------
def signed_area(poly):
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return a / 2


def inside(poly, x, y):
    c = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            c = not c
        j = i
    return c


def dist_to_polyline(poly, x, y, closed=True):
    """Shortest distance from (x, y) to the polygon outline, plus the closest point."""
    best = (1e18, (0.0, 0.0))
    n = len(poly)
    for i in range(n if closed else n - 1):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(x - px, y - py)
        if d < best[0]:
            best = (d, (px, py))
    return best


# ---------- fence ----------
class Fence:
    def __init__(self, cfg):
        f = cfg["fence"]
        self.poly = [tuple(p) for p in f["polygon"]]
        self.ccw = signed_area(self.poly) > 0
        self.heights = f["strand_heights_m"]
        self.kv = f["energizer_kv"]
        self._build_posts(f["post_spacing_m"], f["gate_width_m"])
        self.faults = cfg.get("faults", [])
        self._apply_faults()

    def outward(self, dx, dy):
        L = math.hypot(dx, dy) or 1.0
        dx, dy = dx / L, dy / L
        # CCW: the inside is left of the edge -> the outside is on the right
        return (dy, -dx) if self.ccw else (-dy, dx)

    def _build_posts(self, spacing, gate):
        poly = self.poly
        n = len(poly)
        posts = []  # dict: x, y, s, out(nx,ny), tan(tx,ty), corner
        s = 0.0
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            L = math.hypot(bx - ax, by - ay)
            last = i == n - 1
            usable = L - gate if last else L
            k = max(1, math.ceil(usable / spacing))
            tx, ty = (bx - ax) / L, (by - ay) / L
            out = self.outward(bx - ax, by - ay)
            for j in range(k):
                t = j * usable / k
                posts.append(dict(x=ax + tx * t, y=ay + ty * t, s=s + t, out=out, tan=(tx, ty), corner=(j == 0)))
            if last:
                posts.append(dict(x=ax + tx * usable, y=ay + ty * usable, s=s + usable, out=out, tan=(tx, ty), corner=True, gate=True))
            s += L
        self.posts = posts
        self.length = posts[-1]["s"]
        self.perimeter = s
        for p in posts:
            p["tilt"] = 0.0

    def _apply_faults(self):
        self.broken = set()   # (segment, strand)
        self.breaks = []      # (segment, strand, onset_s)
        self.shorts = []      # (s_along, load, onset_s)
        for ft in self.faults:
            t = ft["type"]
            onset = float(ft.get("onset_s", 0.0))
            if t == "wire_break":
                self.broken.add((ft["segment"], ft.get("strand", 1)))
                self.breaks.append((ft["segment"], ft.get("strand", 1), onset))
            elif t == "post_down":
                self.posts[ft["post"]]["tilt"] = math.radians(62)
                self.shorts.append((self.posts[ft["post"]]["s"], 0.35, onset))
            elif t == "branch_short":
                self.shorts.append((self.segment_mid(ft["segment"])[2], 0.55, onset))

    def attach(self, i, strand):
        """3D point where wire `strand` is attached to post i (accounts for a leaning post)."""
        p = self.posts[i]
        h = self.heights[strand]
        a = p["tilt"]
        ox, oy = p["out"]
        return (p["x"] + ox * math.sin(a) * h, p["y"] + oy * math.sin(a) * h, math.cos(a) * h)

    def segment_mid(self, k):
        a, b = self.posts[k], self.posts[k + 1]
        return ((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2, (a["s"] + b["s"]) / 2)

    def fault_anchor(self, ft):
        if ft["type"] == "post_down":
            p = self.posts[ft["post"]]
            return p["x"], p["y"], p["s"]
        return self.segment_mid(ft["segment"])

    def fault_out(self, ft):
        if ft["type"] == "post_down":
            return self.posts[ft["post"]]["out"]
        return self.posts[ft["segment"]]["out"]

    def fault_where(self, ft):
        """Where the fault is, in both languages: {"en": ..., "ro": ...}."""
        if ft["type"] == "post_down":
            return i18n.both(i18n.WHERE["post"], post=ft["post"])
        k = ft["segment"]
        return i18n.both(i18n.WHERE["segment"], a=k, b=k + 1)

    def voltage(self, strand, s, t=None):
        """Voltage (kV) on wire `strand` at distance s from the energizer (simple model).

        `t` is the time in seconds since the start of the scenario: a fault with `onset_s`
        only counts once it has happened. Without `t` every fault counts.
        """
        def active(onset):
            return t is None or onset <= t
        shorts = [(ss, load) for ss, load, onset in self.shorts if active(onset)]
        v = self.kv / (1 + sum(load for _, load in shorts)) - 0.0015 * s
        for s_short, _ in shorts:
            if s > s_short:
                v -= 0.4
        for seg, st, onset in self.breaks:
            if st == strand and s > self.posts[seg]["s"] and active(onset):
                return 0.0
        return max(0.0, v)

    def gate(self):
        """The gate between the last post and the first one: centre, outward normal, direction."""
        a, b = self.posts[-1], self.posts[0]
        tx, ty = b["x"] - a["x"], b["y"] - a["y"]
        L = math.hypot(tx, ty) or 1.0
        return dict(a=(a["x"], a["y"]), b=(b["x"], b["y"]), center=((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2),
                    out=self.outward(tx, ty), tan=(tx / L, ty / L), width=L)

    def nearest_s(self, x, y):
        """Distance along the fence of the point closest to (x, y), plus the lateral distance."""
        best = (1e18, 0.0)
        P = self.posts
        for i in range(len(P) - 1):
            ax, ay, bx, by = P[i]["x"], P[i]["y"], P[i + 1]["x"], P[i + 1]["y"]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy or 1e-12
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
            d = math.hypot(x - ax - t * dx, y - ay - t * dy)
            if d < best[0]:
                best = (d, P[i]["s"] + t * (P[i + 1]["s"] - P[i]["s"]))
        return best[1], best[0]


# ---------- ground station ----------
def ground_station(cfg, fence):
    """Mast position and camera aims for the ground station (Jetson on a pole near the gate)."""
    gs = dict(cfg.get("ground_station", {}))
    g = fence.gate()
    (gx, gy), (ox, oy), (tx, ty) = g["center"], g["out"], g["tan"]
    off_out, off_side = gs.get("mast_offset_m", [8.0, -8.0])
    mx, my = gs.get("position", [gx + ox * off_out + tx * off_side, gy + oy * off_out + ty * off_side])
    cx = sum(p[0] for p in fence.poly) / len(fence.poly)
    cy = sum(p[1] for p in fence.poly) / len(fence.poly)
    h = gs.get("mast_height_m", 4.5)
    rgb_target = ((gx + cx) / 2, (gy + cy) / 2)
    cams = {
        "rgb": dict(pos=(mx, my, h), yaw=math.atan2(rgb_target[1] - my, rgb_target[0] - mx), pitch=math.radians(12),
                    hfov=math.radians(110), size=(640, 360), fps=10, range=120.0),
        "thermal": dict(pos=(mx, my, h - 0.25), yaw=math.atan2(cy - my, cx - mx), pitch=math.radians(9),
                        hfov=math.radians(50), size=(320, 240), fps=9, range=150.0),
        # iToF on the gate post, looking down at the opening (short range, like a real ToF sensor)
        "depth": dict(pos=(g["a"][0] + ox * 0.3, g["a"][1] + oy * 0.3, 2.4), yaw=math.atan2(ty, tx), pitch=math.radians(50),
                      hfov=math.radians(70), size=(320, 240), fps=10, range=8.0),
    }
    # mast cameras sit on a short arm in front of the pole, so the pole is not in the picture
    for name in ("rgb", "thermal"):
        c = cams[name]
        c["pos"] = (mx + 0.35 * math.cos(c["yaw"]), my + 0.35 * math.sin(c["yaw"]), c["pos"][2])
    for name, c in cams.items():
        c.update(gs.get("cameras", {}).get(name, {}))
    return dict(mast=(mx, my), height=h, gate=g, cams=cams,
                alarm_kv=gs.get("voltage_alarm_kv", 3.0))


def in_camera_view(cam, x, y, z=0.8):
    """Is the world point inside the camera's field of view and range (pinhole, no occlusion)?"""
    px, py, pz = cam["pos"]
    dx, dy, dz = x - px, y - py, z - pz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist > cam["range"] or dist < 0.3:
        return False
    cyaw, syaw = math.cos(cam["yaw"]), math.sin(cam["yaw"])
    fwd_h = dx * cyaw + dy * syaw          # along the camera heading
    side = -dx * syaw + dy * cyaw          # to the left
    cp, sp = math.cos(cam["pitch"]), math.sin(cam["pitch"])
    fwd = fwd_h * cp - dz * sp             # optical axis (pitched down)
    up = fwd_h * sp + dz * cp
    if fwd <= 0.1:
        return False
    th = math.tan(cam["hfov"] / 2)
    tv = th * cam["size"][1] / cam["size"][0]
    return abs(side / fwd) <= th and abs(up / fwd) <= tv


# ---------- drone path ----------
def mission_path(cfg, fence):
    """Closed route along the outside of the fence, rounded corners, starting next to home."""
    m = cfg["mission"]
    off = m["offset_outside_m"]
    poly = fence.poly
    n = len(poly)
    pts = []
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        L = math.hypot(bx - ax, by - ay)
        ox, oy = fence.outward(bx - ax, by - ay)
        steps = max(2, int(L // 2))
        for j in range(steps):
            t = j / steps
            pts.append((ax + (bx - ax) * t + ox * off, ay + (by - ay) * t + oy * off))
    # Chaikin smoothing: rounded corners -> smooth flight
    for _ in range(4):
        new = []
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            new.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            new.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = new
    # start at the point closest to the first post (the energizer)
    p0 = fence.posts[0]
    start = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - p0["x"], pts[i][1] - p0["y"]))
    pts = pts[start:] + pts[:start]
    pts.append(pts[0])
    # resample at a constant spacing
    spacing = m["waypoint_spacing_m"]
    out = [pts[0]]
    acc = 0.0
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        seg = math.hypot(bx - ax, by - ay)
        while acc + seg >= spacing:
            t = (spacing - acc) / seg
            ax, ay = ax + (bx - ax) * t, ay + (by - ay) * t
            out.append((ax, ay))
            seg = math.hypot(bx - ax, by - ay)
            acc = 0.0
        acc += seg
    out.append(pts[-1])
    return out


# ---------- herd ----------
def herd_layout(cfg, fence):
    rnd = random.Random(cfg.get("seed", 1))
    poly = fence.poly
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    animals = []
    placed = []

    def free(x, y, r=3.0):
        return all(math.hypot(x - a, y - b) > r for a, b in placed)

    idx = {"cow": 0, "sheep": 0}
    for kind, count in (("cow", cfg["herd"]["cows"]), ("sheep", cfg["herd"]["sheep"])):
        for _ in range(count):
            for _try in range(500):
                x = rnd.uniform(min(xs), max(xs))
                y = rnd.uniform(min(ys), max(ys))
                if inside(poly, x, y) and dist_to_polyline(poly, x, y)[0] > 7 and free(x, y):
                    break
            idx[kind] += 1
            aid = ("C%02d" if kind == "cow" else "S%02d") % idx[kind]
            placed.append((x, y))
            animals.append(dict(id=aid, kind=kind, x=x, y=y, yaw=rnd.uniform(-math.pi, math.pi), escaped=False,
                                breed=rnd.choice(["holstein", "simmental", "brown_swiss"]) if kind == "cow" else "sheep"))
    # escaped animals: move some of the herd outside, next to a fault
    faults = {f["id"]: f for f in cfg["faults"]}
    for e in cfg.get("escaped", []):
        ft = faults[e["near_fault"]]
        ax, ay, _ = fence.fault_anchor(ft)
        ox, oy = fence.fault_out(ft)
        tx, ty = -oy, ox
        cand = [a for a in animals if a["kind"] == e["kind"] and not a["escaped"]]
        if not cand:
            continue
        a = cand[-1]
        jitter = rnd.uniform(-8, 8)
        a["x"] = ax + ox * e["distance_m"] + tx * jitter
        a["y"] = ay + oy * e["distance_m"] + ty * jitter
        a["escaped"] = True
        a["home"] = (a["x"], a["y"])
    return animals
