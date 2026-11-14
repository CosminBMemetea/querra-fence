"""Geometria pășunii: gard, stâlpi, defecte, traseu dronă, conversii GPS.

Doar stdlib, ca să meargă și cu Python-ul din .venv (pymavlink),
și cu cel din mediul Gazebo (pixi).
Coordonate locale: x = est, y = nord (ENU), în metri; originea = platforma dronei.
"""
import json
import math
import os
import random

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
    """Distanța minimă de la (x, y) la conturul poligonului, plus punctul cel mai apropiat."""
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
        # CCW: interiorul e în stânga muchiei -> exteriorul în dreapta
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
        self.shorts = []      # (s_along, load)
        for ft in self.faults:
            t = ft["type"]
            if t == "wire_break":
                self.broken.add((ft["segment"], ft.get("strand", 1)))
            elif t == "post_down":
                self.posts[ft["post"]]["tilt"] = math.radians(62)
                self.shorts.append((self.posts[ft["post"]]["s"], 0.35))
            elif t == "branch_short":
                self.shorts.append((self.segment_mid(ft["segment"])[2], 0.55))

    def attach(self, i, strand):
        """Punctul 3D unde firul `strand` se prinde de stâlpul i (ține cont de înclinare)."""
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
        if ft["type"] == "post_down":
            return "stâlpul %d" % ft["post"]
        k = ft["segment"]
        return "între stâlpii %d–%d" % (k, k + 1)

    def voltage(self, strand, s):
        """Tensiunea (kV) pe firul `strand` la distanța s de energizator (model simplu)."""
        load = sum(l for _, l in self.shorts)
        v = self.kv / (1 + load) - 0.0015 * s
        for s_short, _ in self.shorts:
            if s > s_short:
                v -= 0.4
        for (seg, st) in self.broken:
            if st == strand and s > self.posts[seg]["s"]:
                return 0.0
        return max(0.0, v)

    def nearest_s(self, x, y):
        """Distanța de-a lungul gardului a celui mai apropiat punct de (x, y) + distanța laterală."""
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


# ---------- drone path ----------
def mission_path(cfg, fence):
    """Traseu închis pe lângă gard (în exterior), cu colțuri rotunjite, pornind lângă casă."""
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
    # Chaikin: colțuri rotunde -> zbor fluid
    for _ in range(4):
        new = []
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            new.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            new.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = new
    # pornim de la punctul cel mai apropiat de primul stâlp (energizator)
    p0 = fence.posts[0]
    start = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - p0["x"], pts[i][1] - p0["y"]))
    pts = pts[start:] + pts[:start]
    pts.append(pts[0])
    # reeșantionare la distanță constantă
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
            aid = ("V%02d" if kind == "cow" else "O%02d") % idx[kind]
            placed.append((x, y))
            animals.append(dict(id=aid, kind=kind, x=x, y=y, yaw=rnd.uniform(-math.pi, math.pi), escaped=False,
                                breed=rnd.choice(["holstein", "baltata", "bruna"]) if kind == "cow" else "oaie"))
    # evadatele: le mutăm pe unele din turmă afară, lângă defect
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
