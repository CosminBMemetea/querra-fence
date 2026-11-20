"""Auto-labelled YOLO dataset from the Gazebo pasture (ground truth from geo.py / gen_world.py).

For each random farm layout (fence polygon, faults, herd, light, ground colour) it writes a world
with a free-flying copy of the drone's inspection camera (640x400, hfov 1.204 rad), starts a
headless Gazebo, moves the camera to random drone-like poses (altitude, pitch, yaw, small roll),
grabs the rendered frame and projects the known 3D geometry into it to write YOLO labels.

Classes: 0 post, 1 wire, 2 wire_break, 3 fallen_post, 4 branch, 5 cow, 6 sheep
Run with tools/make_dataset.sh (Gazebo Python env). Output: $QF_DATASET (default ~/querra-data/fence_yolo)
Occlusion is ignored (a post behind a tree keeps its box); boxes come from dense 3D samples.
"""
import argparse
import copy
import math
import os
import random
import re
import struct
import subprocess
import sys
import threading
import time
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import geo  # noqa: E402
import gen_world  # noqa: E402

# The detector (model-v0.1..v0.3) was trained on the original flat-green world, and write_world() below edits that
# world's light and ground XML by exact string. Keep the dataset on the "classic" look; a dataset in the "rich" look
# needs its own lighting/ground randomisation first.
gen_world.LOOK = os.environ.get("GARDIAN_DATASET_LOOK", "classic")

from gz.transport13 import Node  # noqa: E402
from gz.msgs10.image_pb2 import Image  # noqa: E402
from gz.msgs10.pose_pb2 import Pose  # noqa: E402
from gz.msgs10.boolean_pb2 import Boolean  # noqa: E402

BASE_CONFIG = geo.load_config
CLASSES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]
W, H, HFOV = 640, 400, 1.204
FX = (W / 2) / math.tan(HFOV / 2)
WORLD = "pasture"


# ---------------------------------------------------------------- layouts
STYLE = {"v": "v1", "mission": False}
DEAD_COLOURS = {"grey": (0.35, 0.33, 0.30), "live": None, "dull": (0.62, 0.58, 0.45), "dark": (0.22, 0.22, 0.22)}


def break_rods(a, b, style):
    """Rods of a broken strand between attach points a and b (the same geometry in the world and the labels)."""
    def at(p0, p1, t, z):
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, z)
    out = []
    if style == "hang":       # both ends hang down to the ground (v1)
        for (p0, p1, frac) in ((a, b, 0.32), (b, a, 0.38)):
            mid = at(p0, p1, 0.12, p0[2] * 0.35)
            out += [(p0, mid), (mid, at(p0, p1, frac, 0.02))]
    elif style == "ground":   # snapped wire lying along the fence line on the grass
        for (p0, p1, frac) in ((a, b, 0.45), (b, a, 0.48)):
            g = at(p0, p1, 0.06, 0.02)
            out += [(p0, g), (g, at(p0, p1, frac, 0.02))]
    else:                     # one_end: still tied at one post, the loose end drags on the ground past mid-span
        g = at(a, b, 0.7, 0.03)
        out += [(a, at(a, b, 0.35, a[2] * 0.5)), (at(a, b, 0.35, a[2] * 0.5), g)]
        out += [(b, at(b, a, 0.08, 0.02))]
    return out


def build_fence_v2(fence, render, gate_open=False):
    """gen_world.build_fence with a configurable dead-wire colour and break style."""
    v = gen_world.Visuals()
    P = fence.posts
    WIRE, DEAD = gen_world.WIRE, gen_world.WIRE_DEAD
    if render.get("dead") in DEAD_COLOURS:
        c = DEAD_COLOURS[render["dead"]]
        DEAD = WIRE if c is None else gen_world.mat(*c)
    for i, p in enumerate(P):
        h = 1.35 if p["corner"] else 1.2
        r = 0.075 if p["corner"] else 0.05
        a = p["tilt"]
        ox, oy = p["out"]
        top = (p["x"] + ox * math.sin(a) * h, p["y"] + oy * math.sin(a) * h, math.cos(a) * h)
        v.rod((p["x"], p["y"], 0.0), top, r, gen_world.WOOD if not p["corner"] else gen_world.WOOD_DARK, shadows=True)
    broken_seg = {seg: st for (seg, st) in fence.broken}
    styles = render.get("break_styles", {})
    for k in range(len(P) - 1):
        for st in range(len(fence.heights)):
            a, b = fence.attach(k, st), fence.attach(k + 1, st)
            if broken_seg.get(k) == st:
                for p0, p1 in break_rods(a, b, styles.get(str(k), "hang")):
                    v.rod(p0, p1, 0.018, DEAD)
                continue
            dead = any(bs == st and k > seg for seg, bs in fence.broken)
            v.rod(a, b, 0.018, DEAD if dead else WIRE)
    g, f0 = P[-1], P[0]
    mat = gen_world.mat
    v.rod((g["x"], g["y"], 1.0), (f0["x"], f0["y"], 1.0), 0.012, WIRE)
    v.box((0.25, 0.06, 0.06), ((g["x"] + f0["x"]) / 2, (g["y"] + f0["y"]) / 2, 1.0, 0, 0, math.atan2(f0["y"] - g["y"], f0["x"] - g["x"])), mat(0.08, 0.08, 0.08))
    ox, oy = f0["out"]
    ex, ey = f0["x"] + ox * 0.35, f0["y"] + oy * 0.35
    v.box((0.32, 0.22, 0.38), (ex, ey, 1.05, 0, 0, 0), mat(0.18, 0.2, 0.22))
    v.sphere(0.04, (ex + ox * 0.12, ey + oy * 0.12, 1.2, 0, 0, 0), mat(1, 0.1, 0.05, emissive=(1, 0.1, 0.05)), shadows=False)
    s1 = P[2]
    v.box((0.3, 0.01, 0.16), (s1["x"] + s1["out"][0] * 0.06, s1["y"] + s1["out"][1] * 0.06, 0.8, 0, 0, math.atan2(s1["tan"][1], s1["tan"][0])), mat(0.98, 0.8, 0.05))
    return v


def random_layout(seed):
    rnd = random.Random(seed)
    if STYLE["mission"]:
        cfg = copy.deepcopy(BASE_CONFIG())
        cfg["_render"] = {"dead": "grey", "break_styles": {}}
        return cfg, None
    base = BASE_CONFIG()
    cfg = copy.deepcopy(base)
    cfg["seed"] = seed
    n = rnd.randint(6, 9)
    cx, cy, r0 = 65.0, 55.0, rnd.uniform(38, 60)
    angs = sorted(2 * math.pi * (i + rnd.uniform(-0.25, 0.25)) / n for i in range(n))
    poly = [[round(cx + math.cos(a) * r0 * rnd.uniform(0.75, 1.2), 1), round(cy + math.sin(a) * r0 * rnd.uniform(0.75, 1.2), 1)] for a in angs]
    cfg["fence"]["polygon"] = poly
    cfg["fence"]["post_spacing_m"] = round(rnd.uniform(4.5, 7.0), 1)
    lo = round(rnd.uniform(0.4, 0.6), 2)
    cfg["fence"]["strand_heights_m"] = [lo, round(lo + rnd.uniform(0.35, 0.55), 2)]
    nposts = len(geo.Fence(dict(cfg, faults=[])).posts)
    used, faults = set(), []

    def pick():
        for _ in range(200):
            k = rnd.randint(2, nposts - 4)
            if all(abs(k - u) > 3 for u in used):
                used.add(k)
                return k
        return None
    for i in range(rnd.randint(3, 4) if STYLE["v"] == "v2" else rnd.randint(2, 3)):
        k = pick()
        if k is not None:
            faults.append({"id": "B%d" % i, "type": "wire_break", "segment": k, "strand": rnd.randint(0, 1)})
    for i in range(rnd.randint(1, 2)):
        k = pick()
        if k is not None:
            faults.append({"id": "P%d" % i, "type": "post_down", "post": k})
    for i in range(rnd.randint(1, 2)):
        k = pick()
        if k is not None:
            faults.append({"id": "T%d" % i, "type": "branch_short", "segment": k})
    cfg["faults"] = faults
    if STYLE["v"] == "v2":
        cfg["_render"] = {"dead": rnd.choice(["grey", "grey", "live", "live", "dull", "dark"]),
                          "break_styles": {str(f["segment"]): rnd.choice(["hang", "ground", "one_end"]) for f in faults if f["type"] == "wire_break"}}
    else:
        cfg["_render"] = {"dead": "grey", "break_styles": {}}
    cfg["herd"] = {"cows": rnd.randint(8, 16), "sheep": rnd.randint(6, 12)}
    cfg["escaped"] = [{"kind": rnd.choice(["cow", "cow", "sheep"]), "near_fault": rnd.choice(faults)["id"],
                       "distance_m": rnd.uniform(3, 18)} for _ in range(rnd.randint(3, 6))]
    light = dict(elev=rnd.uniform(25, 80), azim=rnd.uniform(0, 360), intensity=rnd.uniform(0.7, 1.35),
                 ambient=rnd.uniform(0.35, 0.7), tint=rnd.uniform(-0.08, 0.08),
                 ground=(rnd.uniform(0.25, 0.42), rnd.uniform(0.38, 0.52), rnd.uniform(0.12, 0.24)))
    return cfg, light


def write_world(cfg, light, path):
    gen_world.geo.load_config = lambda path=None: cfg
    gen_world.OUT = path
    gen_world.build_fence = lambda fence, gate_open=False: build_fence_v2(fence, cfg["_render"], gate_open)
    gen_world.main()
    s = open(path).read()
    s = re.sub(r"\s*<include>\s*<uri>model://x500_fence</uri>.*?</include>", "", s, flags=re.S)
    if light is None:  # mission world: keep the default sun and ground
        light = dict(elev=None)
    if light["elev"] is None:
        s = s.replace("  </world>", CAM_XML + "\n  </world>")
        with open(path, "w") as f:
            f.write(s)
        return
    el, az = math.radians(light["elev"]), math.radians(light["azim"])
    d = (-math.cos(el) * math.cos(az), -math.cos(el) * math.sin(az), -math.sin(el))
    s = s.replace("<intensity>1.1</intensity>", "<intensity>%.2f</intensity>" % light["intensity"])
    s = s.replace("<direction>-0.45 0.4 -0.8</direction>", "<direction>%.3f %.3f %.3f</direction>" % d)
    a, t = light["ambient"], light["tint"]
    s = s.replace("<ambient>0.55 0.55 0.55 1</ambient>", "<ambient>%.2f %.2f %.2f 1</ambient>" % (a + t, a, a - t))
    g = "%.3f %.3f %.3f 1" % light["ground"]
    s = s.replace("<ambient>0.30 0.45 0.18 1</ambient><diffuse>0.30 0.45 0.18 1</diffuse>",
                  "<ambient>%s</ambient><diffuse>%s</diffuse>" % (g, g))
    cam = CAM_XML
    s = s.replace("  </world>", cam + "\n  </world>")
    with open(path, "w") as f:
        f.write(s)


CAM_XML = ('<model name="ds_cam"><pose>0 0 12 0 0.96 0</pose><link name="link"><gravity>false</gravity>'
           '<inertial><mass>1</mass><inertia><ixx>1</ixx><ixy>0</ixy><ixz>0</ixz><iyy>1</iyy><iyz>0</iyz><izz>1</izz></inertia></inertial>'
           '<sensor name="cam" type="camera"><camera><horizontal_fov>%.3f</horizontal_fov><image><width>%d</width><height>%d</height></image>'
           '<clip><near>0.2</near><far>400</far></clip></camera><always_on>1</always_on><update_rate>30</update_rate>'
           '<topic>/ds_cam/image</topic></sensor></link></model>' % (HFOV, W, H))


# ---------------------------------------------------------------- ground truth as 3D point samples
def line(a, b, n):
    t = np.linspace(0, 1, n)[:, None]
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


def rod(a, b, r, step=0.08):
    n = max(2, int(math.dist(a, b) / step))
    pts = line(a, b, n)
    out = [pts]
    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
        out.append(pts + np.array([dx, dy, 0]))
    return np.vstack(out)


def box_points(cx, cy, yaw, xr, yr, zr, n=6):
    xs, ys, zs = np.linspace(*xr, n), np.linspace(*yr, n), np.linspace(*zr, n)
    g = np.array(np.meshgrid(xs, ys, zs)).reshape(3, -1).T
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([cx + g[:, 0] * c - g[:, 1] * s, cy + g[:, 0] * s + g[:, 1] * c, g[:, 2]], 1)


def ground_truth(cfg):
    f = geo.Fence(cfg)
    P = f.posts
    objs = []  # (class, points, min_inside_fraction)
    for i, p in enumerate(P):
        h = 1.35 if p["corner"] else 1.2
        r = 0.075 if p["corner"] else 0.05
        a = p["tilt"]
        ox, oy = p["out"]
        top = (p["x"] + ox * math.sin(a) * h, p["y"] + oy * math.sin(a) * h, math.cos(a) * h)
        objs.append(("fallen_post" if a > 0.3 else "post", rod((p["x"], p["y"], 0.0), top, r + 0.05, 0.05), 0.5))
    broken = {seg: st for seg, st in f.broken}
    for k in range(len(P) - 1):
        wires = []
        for st in range(len(f.heights)):
            a, b = f.attach(k, st), f.attach(k + 1, st)
            if broken.get(k) == st:
                style = cfg.get("_render", {}).get("break_styles", {}).get(str(k), "hang")
                pts = [line(p0, p1, 30) for p0, p1 in break_rods(a, b, style)]
                objs.append(("wire_break", np.vstack(pts), 0.35))
            else:
                wires.append(line(a, b, 80))
        if wires:
            objs.append(("wire", np.vstack(wires), 0.3))
    g, f0 = P[-1], P[0]
    objs.append(("wire", line((g["x"], g["y"], 1.0), (f0["x"], f0["y"], 1.0), 60), 0.3))
    for ft in cfg["faults"]:
        if ft["type"] == "branch_short":
            ax, ay, _ = f.fault_anchor(ft)
            ox, oy = f.fault_out(ft)
            tx, ty = ax + ox * 4.0, ay + oy * 4.0
            start = (tx - ox * 0.3, ty - oy * 0.3, 3.2)
            end = (ax - ox * 2.2, ay - oy * 2.2, 0.05)
            pts = [rod(start, end, 0.13)]
            for fr in (0.45, 0.7, 0.92):
                c = np.array([start[j] + (end[j] - start[j]) * fr for j in range(3)]) + np.array([0, 0, 0.4])
                u = np.random.default_rng(0).normal(size=(60, 3))
                pts.append(c + 0.75 * u / np.linalg.norm(u, axis=1)[:, None])
            objs.append(("branch", np.vstack(pts), 0.4))
    for a in geo.herd_layout(cfg, f):
        if a["kind"] == "cow":
            pts = box_points(a["x"], a["y"], a["yaw"], (-1.05, 1.55), (-0.4, 0.4), (0, 1.6))
        else:
            pts = box_points(a["x"], a["y"], a["yaw"], (-0.62, 0.8), (-0.36, 0.36), (0, 1.05))
        objs.append((a["kind"], pts, 0.45))
    return f, objs


# ---------------------------------------------------------------- camera
def rot(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return Rz @ Ry @ Rx


def quat(roll, pitch, yaw):
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return (cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy)


def project(pts, c, R):
    d = (pts - c) @ R  # columns of R: forward, left, up
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    front = x > 0.3
    u = np.full(len(pts), -1e9)
    v = np.full(len(pts), -1e9)
    u[front] = W / 2 - FX * y[front] / x[front]
    v[front] = H / 2 - FX * z[front] / x[front]
    return u, v, front, x


def labels_for(objs, c, R):
    out = []
    for cls, pts, min_frac in objs:
        if np.min(np.linalg.norm(pts[:, :2] - c[:2], axis=1)) > 70:
            continue
        u, v, front, depth = project(pts, c, R)
        inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        if inside.sum() < 3 or inside.mean() < min_frac:
            continue
        x0, x1, y0, y1 = u[inside].min(), u[inside].max(), v[inside].min(), v[inside].max()
        if max(x1 - x0, y1 - y0) < (8 if cls in ("post", "wire") else 6):
            continue
        pad = 3
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W - 1, x1 + pad), min(H - 1, y1 + pad)
        out.append((CLASSES.index(cls), (x0 + x1) / 2 / W, (y0 + y1) / 2 / H, (x1 - x0) / W, (y1 - y0) / H))
    return out


def sample_pose(rnd, f, cfg, animals):
    P = f.posts
    if STYLE["mission"] or rnd.random() < (0.6 if STYLE["v"] == "v2" else 0.45):  # like the inspection flight: outside the fence, flying along it
        k = rnd.randrange(len(P) - 1)
        a, b = P[k], P[k + 1]
        t = rnd.random()
        x, y = a["x"] + (b["x"] - a["x"]) * t, a["y"] + (b["y"] - a["y"]) * t
        off = rnd.uniform(0.5, 7)
        if STYLE["mission"]:
            off = rnd.uniform(1.5, 3.5)
        x, y = x + a["out"][0] * off, y + a["out"][1] * off
        yaw = math.atan2(a["tan"][1], a["tan"][0]) + (math.pi if rnd.random() < 0.5 else 0) + math.radians(rnd.uniform(-20, 20))
        alt, pitch = rnd.uniform(7, 17), math.radians(rnd.uniform(42, 68))
        if STYLE["mission"]:
            off, alt, pitch = rnd.uniform(1.5, 3.5), rnd.uniform(11, 13), math.radians(rnd.uniform(52, 58))
    else:  # look at a fault, an animal or a random fence point
        r = rnd.random()
        if r < 0.45 and cfg["faults"]:
            tx, ty, _ = f.fault_anchor(rnd.choice(cfg["faults"]))
        elif r < 0.75:
            an = rnd.choice(animals)
            tx, ty = an["x"], an["y"]
        else:
            p = rnd.choice(P)
            tx, ty = p["x"], p["y"]
        tx, ty = tx + rnd.uniform(-5, 5), ty + rnd.uniform(-5, 5)
        alt, pitch, yaw = rnd.uniform(5, 20), math.radians(rnd.uniform(35, 80)), rnd.uniform(-math.pi, math.pi)
        dist = alt / math.tan(pitch)
        x, y = tx - dist * math.cos(yaw), ty - dist * math.sin(yaw)
    roll = math.radians(rnd.uniform(-5, 5))
    return x, y, alt, roll, pitch, yaw


# ---------------------------------------------------------------- io
def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[i].tobytes() for i in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                 chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


class Frames:
    def __init__(self):
        self.lock = threading.Lock()
        self.count, self.img = 0, None

    def cb(self, msg):
        if msg.width != W or msg.height != H:
            return
        a = np.frombuffer(msg.data, dtype=np.uint8)[: H * msg.step].reshape(H, msg.step)[:, : W * 3].reshape(H, W, 3)
        with self.lock:
            self.img = a.copy()
            self.count += 1

    def wait_new(self, n0, k=3, timeout=5):
        t = time.time()
        while time.time() - t < timeout:
            with self.lock:
                if self.count >= n0 + k:
                    return self.img
            time.sleep(0.005)
        return None


def run_layout(li, seed, n_frames, split, out, args):
    cfg, light = random_layout(seed)
    wpath = os.path.join(out, "worlds", "layout_%02d.sdf" % li)
    os.makedirs(os.path.dirname(wpath), exist_ok=True)
    write_world(cfg, light, wpath)
    f, objs = ground_truth(cfg)
    animals = geo.herd_layout(cfg, f)
    log = open(os.path.join(out, "worlds", "layout_%02d.gz.log" % li), "w")
    gz = subprocess.Popen(["gz", "sim", "-r", "-s", "--verbose=1", wpath], stdout=log, stderr=subprocess.STDOUT)
    node = Node()
    fr = Frames()
    node.subscribe(Image, "/ds_cam/image", fr.cb)
    t0 = time.time()
    while fr.count < 3 and time.time() - t0 < 90:
        time.sleep(0.2)
    if fr.count < 3:
        gz.terminate()
        raise RuntimeError("layout %d: no camera frames (see %s)" % (li, log.name))
    rnd = random.Random(seed * 7 + 1)
    counts = [0] * len(CLASSES)
    saved = 0
    fails = {"set_pose": 0, "no_frame": 0}
    streak = 0
    try:
        while saved < n_frames:
            if streak and streak % 25 == 0:
                print("[dataset] layout %d: %d failures in a row %s, %d saved" % (li, streak, fails, saved), flush=True)
            if streak >= 100:
                raise RuntimeError("layout %d: giving up after %d failures %s" % (li, streak, fails))
            x, y, z, roll, pitch, yaw = sample_pose(rnd, f, cfg, animals)
            req = Pose()
            req.name = "ds_cam"
            req.position.x, req.position.y, req.position.z = x, y, z
            q = quat(roll, pitch, yaw)
            req.orientation.w, req.orientation.x, req.orientation.y, req.orientation.z = q
            with fr.lock:
                n0 = fr.count
            ok, rep = node.request("/world/%s/set_pose" % WORLD, req, Pose, Boolean, 1000)
            if not ok:
                fails["set_pose"] += 1; streak += 1
                time.sleep(0.2)
                continue
            img = fr.wait_new(n0, k=args.settle)
            if img is None:
                fails["no_frame"] += 1; streak += 1
                continue
            streak = 0
            labs = labels_for(objs, np.array([x, y, z]), rot(roll, pitch, yaw))
            if not labs and rnd.random() < 0.7:
                continue  # keep only some empty frames
            name = "L%02d_%04d" % (li, saved)
            write_png(os.path.join(out, "images", split, name + ".png"), img)
            with open(os.path.join(out, "labels", split, name + ".txt"), "w") as fh:
                for c, cx, cy, bw, bh in labs:
                    fh.write("%d %.6f %.6f %.6f %.6f\n" % (c, cx, cy, bw, bh))
                    counts[c] += 1
            saved += 1
    finally:
        gz.terminate()
        try:
            gz.wait(10)
        except subprocess.TimeoutExpired:
            gz.kill()
        subprocess.run(["pkill", "-f", wpath])
        log.close()
    print("[dataset] layout %d (%s, seed %d): %d frames in %.0f s, faults %s, light elev %.0f, boxes %s" % (
        li, split, seed, saved, time.time() - t0, [ft["type"] for ft in cfg["faults"]], (light or {}).get("elev") or 0,
        dict(zip(CLASSES, counts))), flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("QF_DATASET", os.path.expanduser("~/querra-data/fence_yolo")))
    ap.add_argument("--layouts", type=int, default=10)
    ap.add_argument("--val-layouts", type=int, default=2)
    ap.add_argument("--frames", type=int, default=350)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--settle", type=int, default=3, help="frames to wait after moving the camera")
    ap.add_argument("--style", choices=("v1", "v2"), default="v1", help="v2: 3-4 breaks, varied dead-wire colour, varied break shapes, more flight-like poses")
    ap.add_argument("--split", choices=("train", "val", "test"), help="force every layout into this split")
    ap.add_argument("--mission-world", action="store_true", help="the real fence.json pasture with flight-like poses only (evaluation)")
    args = ap.parse_args()
    for d in ("images/train", "images/val", "images/test", "labels/train", "labels/val", "labels/test"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    with open(os.path.join(args.out, "data.yaml"), "w") as fh:
        fh.write("path: %s\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n" % args.out +
                 "".join("  %d: %s\n" % (i, c) for i, c in enumerate(CLASSES)))
    for li in range(args.start, args.layouts):
        split = args.split or ("val" if li >= args.layouts - args.val_layouts else "train")
        STYLE.update(v=args.style, mission=args.mission_world)
        for attempt in range(3):
            try:
                run_layout(li, args.seed + li, args.frames, split, args.out, args)
                break
            except RuntimeError as exc:
                print("[dataset] %s, retrying" % exc, flush=True)


if __name__ == "__main__":
    main()
