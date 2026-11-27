"""Auto-labelled YOLO dataset for the ground robot's side camera, from random Gazebo forests (labels from geometry).

For each random forest enclosure (fence polygon, post spacing, strand heights, faults, forest density, sun) it writes
the forest world without the robot, adds a free copy of the robot's side camera (640x400, 100 deg, the same as
gen_forest.ROBOT["camera"]) plus a depth camera on the same mount, starts a headless Gazebo, and places the camera at
robot-like poses: on the patrol strip 1.4-2.5 m outside the fence, 0.70 m up, looking left at the fence and a little
down, with the heading, pitch and roll a driving robot has. Each frame is labelled by projecting the known 3D geometry
(tools/make_dataset.py's ground_truth, plus the forest's own branch shape); the depth image removes the parts a trunk
or a bush hides, which the drone's generator ignores.

Classes (the drone's, so model-v0.5 can be fine-tuned): 0 post, 1 wire, 2 wire_break, 3 fallen_post, 4 branch, 5 cow, 6 sheep
(no animals in the forest).

  tools/make_ground_dataset.sh [--layouts 14 --val-layouts 2 --frames 300 --seed 500 --out ~/querra-data/ground_yolo]
  tools/make_ground_dataset.sh --split test --seed 900 --layouts 3 --frames 200 --out ...      held-out layouts
  tools/make_ground_dataset.sh --patrol --out ...    the real forest.json world along its patrol route (never trained on)
  tools/make_ground_dataset.sh --patrol --patrol-seed 700 --out ...   a new random forest (random_forest(700), as the
                                                     training layouts but from seeds never trained on) along its route
  --preview N also writes the first N frames with their boxes drawn (preview/), to check the labels by eye.
  --focus post_down --posts-down 4-6: layouts with more fallen posts and most poses near them (ground-v0.2's extra data).
  --fence-look steel|polywire|polyrope|polytape: real fence conductors at their real size instead of the classic
  3.6 cm glowing yellow rods (sim/gen_world.py FENCE_LOOKS); the layouts, poses and labels stay the same. A list
  (steel,polywire,polyrope) gives the layouts one look each, in turn: a training set with a mix of fences.
  --supersample 3 renders the colour camera 3x wider and taller and averages each 3x3 block in linear light, as a sensor
  gathers it: a 2.5 mm wire 2 m away covers half a pixel and should show as a faint line, not as dots or nothing. The
  colour camera then runs at fewer frames per second (cam_rate), so its larger frames do not pile up.
  --width 1280: a camera of the same lens and aspect, 1280 pixels wide (the robot's is 640): how much a better camera
  sees of a thin wire. The labels' pixel sizes (smallest box, padding) scale with it, so they match across widths.
"""
import argparse
import copy
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import geo  # noqa: E402
import gen_forest  # noqa: E402
import gen_world  # noqa: E402   (FENCE_LOOK)
import make_dataset as md  # noqa: E402  (ground_truth, rod, rot, quat, write_png, CLASSES)
from supersample import TO_LINEAR, cam_rate, downsample, rgb  # noqa: E402,F401  (TO_LINEAR, downsample: tests)

from gz.transport13 import Node  # noqa: E402
from gz.msgs10.image_pb2 import Image  # noqa: E402
from gz.msgs10.pose_pb2 import Pose  # noqa: E402
from gz.msgs10.boolean_pb2 import Boolean  # noqa: E402

CAM = gen_forest.ROBOT["camera"]
W, H, HFOV = CAM["width"], CAM["height"], math.radians(CAM["hfov_deg"])
FX = (W / 2) / math.tan(HFOV / 2)
SCALE = 1.0                                        # W / the robot camera's width (--width): pixel sizes in the labels scale


def set_width(w):
    """A camera of the same lens w pixels wide (--width): the labels' pixel sizes scale with it."""
    global W, H, FX, SCALE
    W, H, SCALE = w, round(w * CAM["height"] / CAM["width"]), w / CAM["width"]
    FX = (W / 2) / math.tan(HFOV / 2)


CAM_Z, CAM_PITCH, CAM_SIDE = 0.70, CAM["rpy"][1], CAM["xyz"][1]   # 0.28 m base link + 0.42 m mount; 0.10 rad down
CLASSES = md.CLASSES
WORLD = "forest"
FOREST_CFG = os.path.join(ROOT, "forest.json")
MAX_RANGE = 12.0                                  # do not label fence parts farther than this (tiny, or across the enclosure)
# The robot drives under a fallen branch (it crosses the strip from a tree outside), so only part of it is ever in front
# of the camera; its leaf balls also hide their own far side from the depth camera.
MIN_FRAC = {"branch": 0.15, "fallen_post": 0.3}   # share of the object's points inside the frame (else the drone's)
DEPTH_TOL = {"branch": 1.5}                       # metres behind the depth image still counted as seen (else 0.25)

def cam_xml(ss=1):
    """The dataset cameras: colour at ss times the robot camera's size (averaged back down in Frames), depth at its size."""
    return ('<model name="ds_cam"><pose>0 0 0.7 0 0 0</pose><link name="link"><gravity>false</gravity>'
            '<inertial><mass>1</mass><inertia><ixx>1</ixx><ixy>0</ixy><ixz>0</ixz><iyy>1</iyy><iyz>0</iyz><izz>1</izz></inertia></inertial>'
            '<sensor name="cam" type="camera"><camera><horizontal_fov>{f:.4f}</horizontal_fov><image><width>{sw}</width><height>{sh}</height></image>'
            '<clip><near>0.1</near><far>80</far></clip></camera><always_on>1</always_on><update_rate>{rate}</update_rate>'
            '<topic>/ds_cam/image</topic></sensor>'
            '<sensor name="depth" type="depth_camera"><camera><horizontal_fov>{f:.4f}</horizontal_fov><image><width>{w}</width><height>{h}</height>'
            '<format>R_FLOAT32</format></image><clip><near>0.1</near><far>80</far></clip></camera><always_on>1</always_on>'
            '<update_rate>{drate}</update_rate><topic>/ds_cam/depth</topic></sensor></link></model>').format(
        f=HFOV, w=W, h=H, sw=W * ss, sh=H * ss, rate=cam_rate(ss, W, H), drate=cam_rate(1, W, H))


CAM_XML = cam_xml(1)


# ---------------------------------------------------------------- layouts
def random_forest(seed, posts_down=(2, 3)):
    """A random enclosure in the forest style: forest.json with a new polygon, posts, faults, forest and sun."""
    rnd = random.Random(seed)
    cfg = copy.deepcopy(geo.load_config(FOREST_CFG))
    cfg["seed"] = seed
    n = rnd.randint(6, 9)
    cx, cy, r0 = 85.0, 50.0, rnd.uniform(45, 70)
    angs = sorted(2 * math.pi * (i + rnd.uniform(-0.25, 0.25)) / n for i in range(n))
    cfg["fence"]["polygon"] = [[round(cx + math.cos(a) * r0 * rnd.uniform(0.75, 1.2), 1),
                                round(cy + math.sin(a) * r0 * rnd.uniform(0.75, 1.2), 1)] for a in angs]
    cfg["fence"]["post_spacing_m"] = round(rnd.uniform(3.5, 5.5), 1)
    lo = round(rnd.uniform(0.40, 0.65), 2)
    cfg["fence"]["strand_heights_m"] = [lo, round(lo + rnd.uniform(0.35, 0.55), 2)]
    nposts = len(geo.Fence(dict(cfg, faults=[])).posts)
    used, faults = set(), []

    def pick():
        for _ in range(200):
            k = rnd.randint(3, nposts - 5)
            if all(abs(k - u) > 4 for u in used):
                used.add(k)
                return k
        return None
    for i in range(rnd.randint(3, 5)):
        k = pick()
        if k is not None:
            faults.append({"id": "B%d" % i, "type": "wire_break", "segment": k, "strand": rnd.randint(0, 1)})
    for i in range(rnd.randint(*posts_down)):
        k = pick()
        if k is not None:
            faults.append({"id": "P%d" % i, "type": "post_down", "post": k})
    for i in range(rnd.randint(2, 3)):
        k = pick()
        if k is not None:
            faults.append({"id": "T%d" % i, "type": "branch_short", "segment": k})
    cfg["faults"] = faults
    fo = cfg["forest"]
    fo.update(band_m=rnd.uniform(16, 26), tree_spacing_m=rnd.uniform(4.0, 5.6), fir_share=rnd.uniform(0.15, 0.5),
              pinch_points=rnd.randint(3, 8), logs=rnd.randint(4, 10), rocks=rnd.randint(6, 16),
              meadow_edges=rnd.sample(range(n), rnd.randint(0, 2)))
    cfg["herd"], cfg["escaped"] = {"cows": 0, "sheep": 0}, []
    sun = dict(elev=rnd.uniform(20, 70), azim=rnd.uniform(0, 360), intensity=rnd.uniform(0.8, 1.4),
               ambient=rnd.uniform(0.30, 0.50), fill=rnd.uniform(0.15, 0.4), warm=rnd.uniform(-0.06, 0.08))
    return cfg, sun


def patrol_forest():
    cfg = copy.deepcopy(geo.load_config(FOREST_CFG))
    cfg["herd"], cfg["escaped"] = {"cows": 0, "sheep": 0}, []
    return cfg, None


def write_world(cfg, sun, path, ss=1):
    """gen_forest's world for cfg at path, without the robot, with the dataset cameras, the sun randomised."""
    d = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    saved = (geo.load_config, gen_forest.OUT, gen_forest.META, gen_forest.GROUND_OBJ, gen_forest.ROBOT_SDF)
    try:
        geo.load_config = lambda p=None: cfg
        gen_forest.OUT, gen_forest.META = path, os.path.join(d, base + "_meta.json")
        gen_forest.GROUND_OBJ = os.path.join(d, base + "_ground", "meshes", "ground.obj")
        gen_forest.ROBOT_SDF = os.path.join(d, "_robot", "model.sdf")
        os.makedirs(os.path.dirname(gen_forest.GROUND_OBJ), exist_ok=True)
        gen_forest.main()
    finally:
        geo.load_config, gen_forest.OUT, gen_forest.META, gen_forest.GROUND_OBJ, gen_forest.ROBOT_SDF = saved
    s = open(path, encoding="utf-8").read()
    s = re.sub(r"\s*<include>\s*<uri>model://querra_ugv</uri>.*?</include>", "", s, flags=re.S)
    s = s.replace("<uri>model://forest_ground/meshes/ground.obj</uri>",
                  "<uri>file://%s</uri>" % os.path.join(d, base + "_ground", "meshes", "ground.obj"))
    if sun:
        el, az = math.radians(sun["elev"]), math.radians(sun["azim"])
        dvec = (-math.cos(el) * math.cos(az), -math.cos(el) * math.sin(az), -math.sin(el))
        s = s.replace("<intensity>1.15</intensity>", "<intensity>%.2f</intensity>" % sun["intensity"], 1)
        s = s.replace("<direction>0.45 0.35 -0.82</direction>", "<direction>%.3f %.3f %.3f</direction>" % dvec, 1)
        s = s.replace("<diffuse>1.0 0.93 0.82 1</diffuse>",
                      "<diffuse>1.0 %.2f %.2f 1</diffuse>" % (0.93 - sun["warm"], 0.82 - 2 * sun["warm"]), 1)
        s = s.replace("<intensity>0.3</intensity>", "<intensity>%.2f</intensity>" % sun["fill"], 1)
        a = sun["ambient"]
        s = s.replace("<ambient>0.40 0.42 0.44 1</ambient>", "<ambient>%.2f %.2f %.2f 1</ambient>" % (a, a + 0.02, a + 0.04), 1)
    s = s.replace("  </world>", cam_xml(ss) + "\n  </world>")
    open(path, "w", encoding="utf-8").write(s)


# ---------------------------------------------------------------- ground truth
def ground_truth(cfg):
    """The drone generator's posts, wires and breaks, with the forest's own branch shape (gen_forest.build_forest)."""
    f, objs = md.ground_truth(cfg)
    objs = [o for o in objs if o[0] != "branch"]
    for ft in cfg["faults"]:
        if ft["type"] != "branch_short":
            continue
        ax, ay, _ = f.fault_anchor(ft)
        ox, oy = f.fault_out(ft)
        tx, ty = ax + ox * 4.6, ay + oy * 4.6
        start, end = (tx - ox * 0.3, ty - oy * 0.3, 3.4), (ax - ox * 2.0, ay - oy * 2.0, 0.05)
        pts = [md.rod(start, end, 0.12)]
        u = np.random.default_rng(0).normal(size=(80, 3))
        u = 0.7 * u / np.linalg.norm(u, axis=1)[:, None]
        for fr in (0.5, 0.75, 0.93):
            c = np.array([start[j] + (end[j] - start[j]) * fr for j in range(3)]) + np.array([0, 0, 0.35])
            pts.append(c + u)
        objs.append(("branch", np.vstack(pts), 0.4))
    return f, objs


def project(pts, c, R):
    d = (pts - c) @ R                      # columns of R: forward, left, up
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    front = x > 0.15
    u = np.full(len(pts), -1e9)
    v = np.full(len(pts), -1e9)
    u[front] = W / 2 - FX * y[front] / x[front]
    v[front] = H / 2 - FX * z[front] / x[front]
    return u, v, front, x


def labels_for(objs, c, R, depth):
    """YOLO boxes of the objects in view; points hidden behind something nearer (the depth image) do not count."""
    out = []
    for cls, pts, min_frac in objs:
        min_frac = MIN_FRAC.get(cls, min_frac)
        if np.min(np.linalg.norm(pts[:, :2] - c[:2], axis=1)) > MAX_RANGE:
            continue
        u, v, front, x = project(pts, c, R)
        inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        if inside.sum() < 3 or inside.mean() < min_frac:
            continue
        seen = inside.copy()
        if depth is not None:
            iu, iv = u[inside].astype(int), v[inside].astype(int)
            dz = depth[iv, iu]
            hidden = np.isfinite(dz) & (dz < x[inside] - (DEPTH_TOL.get(cls, 0.25) + 0.03 * x[inside]))
            seen[np.nonzero(inside)[0][hidden]] = False
        if seen.sum() < 3 or seen.sum() < 0.5 * inside.sum():
            continue
        x0, x1, y0, y1 = u[seen].min(), u[seen].max(), v[seen].min(), v[seen].max()
        if max(x1 - x0, y1 - y0) < 8 * SCALE:
            continue
        pad = 3 * SCALE
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W - 1, x1 + pad), min(H - 1, y1 + pad)
        out.append((CLASSES.index(cls), (x0 + x1) / 2 / W, (y0 + y1) / 2 / H, (x1 - x0) / W, (y1 - y0) / H))
    return out


# ---------------------------------------------------------------- camera poses
class Strips:
    """Patrol strips at several distances outside the fence (gen_forest's offset polygon), sampled every 0.25 m."""
    def __init__(self, fence, dists=(1.4, 1.6, 1.8, 1.9, 2.0, 2.2, 2.5)):
        self.strips = {}
        for d in dists:
            pts, length = gen_forest.sample_loop(gen_forest.offset_polygon(fence, d), 0.25, 0.0)
            self.strips[d] = (np.array(pts), length)
        self.fence = fence

    def pose_at(self, d, s):
        pts, length = self.strips[d]
        i = int((s % length) / 0.25) % (len(pts) - 1)
        a, b = pts[i], pts[i + 1]
        return a[0], a[1], math.atan2(b[1] - a[1], b[0] - a[0])

    def s_near(self, d, x, y):
        pts, _ = self.strips[d]
        return float(np.argmin(np.hypot(pts[:, 0] - x, pts[:, 1] - y))) * 0.25


def camera_pose(rx, ry, ryaw, rnd, jitter=True):
    """Camera pose on a robot at (rx, ry, ryaw): the mount 0.22 m to the left, 0.70 m up, looking left and down."""
    if jitter:
        ryaw += math.radians(rnd.gauss(0, 4) if rnd.random() < 0.9 else rnd.uniform(-20, 20))
    cx, cy = rx - math.sin(ryaw) * CAM_SIDE, ry + math.cos(ryaw) * CAM_SIDE
    z = CAM_Z + (rnd.gauss(0, 0.025) if jitter else 0.0)
    yaw = ryaw + math.pi / 2 + (math.radians(rnd.gauss(0, 2)) if jitter else 0.0)
    pitch = CAM_PITCH + (rnd.gauss(0, 0.03) if jitter else 0.0)
    roll = rnd.gauss(0, 0.025) if jitter else 0.0
    return cx, cy, z, roll, pitch, yaw


def sample_pose(rnd, strips, cfg, f, focus=None):
    d = rnd.choice(list(strips.strips))
    _, length = strips.strips[d]
    r = rnd.random()
    types = sorted({ft["type"] for ft in cfg["faults"]})
    if r < (0.7 if focus else 0.45) and cfg["faults"]:   # near a fault: in view, or just about to be
        if focus in types and rnd.random() < 0.7:  # --focus: mostly that fault type
            kind = focus
        else:
            kind = rnd.choice(types)              # each fault type equally often
        ft = rnd.choice([ft for ft in cfg["faults"] if ft["type"] == kind])
        ax, ay, _ = f.fault_anchor(ft)
        s = strips.s_near(d, ax, ay) + (rnd.uniform(-3.5, 3.5) if rnd.random() < 0.75 else rnd.uniform(-9, 9))
    else:
        s = rnd.uniform(0, length)
    rx, ry, ryaw = strips.pose_at(d, s)
    lat = rnd.uniform(-0.1, 0.1)                  # between the strips
    rx, ry = rx - math.sin(ryaw) * lat, ry + math.cos(ryaw) * lat
    return camera_pose(rx, ry, ryaw, rnd)


# ---------------------------------------------------------------- frames
class Frames:
    def __init__(self, ss=1):
        self.lock, self.ss = threading.Lock(), ss
        self.count, self.img, self.dcount, self.depth = 0, None, 0, None

    def cb(self, msg):
        sw, sh = W * self.ss, H * self.ss
        if msg.width != sw or msg.height != sh:
            return
        if self.ss > 1:                           # keep the raw bytes; averaged down only for the frames that are saved
            with self.lock:
                self.img, self.step, self.count = msg.data, msg.step, self.count + 1
            return
        a = np.frombuffer(msg.data, dtype=np.uint8)[: H * msg.step].reshape(H, msg.step)[:, : W * 3].reshape(H, W, 3)
        with self.lock:
            self.img, self.count = a.copy(), self.count + 1

    def colour(self, img):
        if self.ss == 1:
            return img
        return downsample(rgb(img, self.step, W * self.ss, H * self.ss), self.ss)

    def dcb(self, msg):
        if msg.width != W or msg.height != H:
            return
        a = np.frombuffer(msg.data, dtype=np.float32)[: H * W].reshape(H, W)
        with self.lock:
            self.depth, self.dcount = a.copy(), self.dcount + 1

    def wait_new(self, n0, d0, k=3, timeout=5):
        t = time.time()
        while time.time() - t < timeout:
            with self.lock:
                if self.count >= n0 + k and self.dcount >= d0 + k:
                    img, depth = self.img, self.depth
                    break
            time.sleep(0.005)
        else:
            return None, None
        return self.colour(img), depth


def draw_boxes(img, labs):
    out = img.copy()
    cols = [(240, 240, 240), (255, 200, 0), (255, 40, 40), (255, 0, 255), (0, 255, 120), (0, 180, 255), (0, 120, 255)]
    for c, cx, cy, bw, bh in labs:
        x0, x1 = int((cx - bw / 2) * W), int((cx + bw / 2) * W) - 1
        y0, y1 = int((cy - bh / 2) * H), int((cy + bh / 2) * H) - 1
        for t in range(2):
            out[max(0, y0 + t), x0:x1] = cols[c]; out[min(H - 1, y1 - t), x0:x1] = cols[c]
            out[y0:y1, max(0, x0 + t)] = cols[c]; out[y0:y1, min(W - 1, x1 - t)] = cols[c]
    return out


def run_layout(li, seed, n_frames, split, out, args):
    if args.patrol and args.patrol_seed is not None:
        cfg, sun = random_forest(args.patrol_seed)
        seed = args.patrol_seed
    else:
        cfg, sun = patrol_forest() if args.patrol else random_forest(seed, args.posts_down)
    gen_world.FENCE_LOOK = args.looks[li % len(args.looks)]
    wpath = os.path.join(out, "worlds", ("patrol" if args.patrol else "layout_%02d" % li) + ".sdf")
    os.makedirs(os.path.dirname(wpath), exist_ok=True)
    write_world(cfg, sun, wpath, args.supersample)
    f, objs = ground_truth(cfg)
    strips = Strips(f)
    log = open(os.path.splitext(wpath)[0] + ".gz.log", "w")
    gz = subprocess.Popen(["gz", "sim", "-r", "-s", "--verbose=1", wpath], stdout=log, stderr=subprocess.STDOUT)
    node = Node()
    fr = Frames(args.supersample)
    node.subscribe(Image, "/ds_cam/image", fr.cb)
    node.subscribe(Image, "/ds_cam/depth", fr.dcb)
    t0 = time.time()
    while (fr.count < 3 or fr.dcount < 3) and time.time() - t0 < 150:
        time.sleep(0.2)
    if fr.count < 3 or fr.dcount < 3:
        gz.terminate()
        raise RuntimeError("layout %d: no camera frames (rgb %d, depth %d; see %s)" % (li, fr.count, fr.dcount, log.name))
    rnd = random.Random(seed * 7 + 1)
    counts, saved, streak = [0] * len(CLASSES), 0, 0
    patrol = None
    if args.patrol:                               # the robot's own route (gen_forest: 1.9 m out, every 0.5 m), no jitter
        meta = json.load(open(os.path.splitext(wpath)[0] + "_meta.json"))
        route = meta["route"]
        patrol = [(route[i][0], route[i][1], math.atan2(route[i + 1][1] - route[i][1], route[i + 1][0] - route[i][0]))
                  for i in range(len(route) - 1)]
        n_frames = len(patrol)
        with open(os.path.join(out, "patrol_faults.json"), "w") as fh:
            json.dump({"faults": meta["faults"], "route": route}, fh)
    try:
        while saved < n_frames:
            if streak >= 100:
                raise RuntimeError("layout %d: giving up after %d failures in a row, %d saved" % (li, streak, saved))
            if patrol:
                x, y, z, roll, pitch, yaw = camera_pose(*patrol[saved], rnd, jitter=False)
            else:
                x, y, z, roll, pitch, yaw = sample_pose(rnd, strips, cfg, f, args.focus)
            req = Pose()
            req.name = "ds_cam"
            req.position.x, req.position.y, req.position.z = x, y, z
            req.orientation.w, req.orientation.x, req.orientation.y, req.orientation.z = md.quat(roll, pitch, yaw)
            with fr.lock:
                n0, d0 = fr.count, fr.dcount
            ok, _ = node.request("/world/%s/set_pose" % WORLD, req, Pose, Boolean, 1000)
            if not ok:
                streak += 1
                time.sleep(0.2)
                continue
            img, depth = fr.wait_new(n0, d0, k=args.settle)
            if img is None:
                streak += 1
                continue
            streak = 0
            labs = labels_for(objs, np.array([x, y, z]), md.rot(roll, pitch, yaw), depth)
            if not patrol and not any(c in (2, 3, 4) for c, *_ in labs) and rnd.random() < 0.35:
                continue                          # keep about two thirds of the frames without a fault
            # G: train and val layouts, T: test layouts (their numbers start at 0 too), P: the patrol
            name = ("P_%04d" % saved) if patrol else "%s%02d_%04d" % ("T" if split == "test" else "G", li, saved)
            md.write_png(os.path.join(out, "images", split, name + ".png"), img)
            with open(os.path.join(out, "labels", split, name + ".txt"), "w") as fh:
                for c, cx, cy, bw, bh in labs:
                    fh.write("%d %.6f %.6f %.6f %.6f\n" % (c, cx, cy, bw, bh))
                    counts[c] += 1
            if patrol:
                with open(os.path.join(out, "patrol_poses.jsonl"), "a") as fh:
                    fh.write(json.dumps({"name": name, "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 4)}) + "\n")
            if saved < args.preview:
                os.makedirs(os.path.join(out, "preview"), exist_ok=True)
                md.write_png(os.path.join(out, "preview", name + ".png"), draw_boxes(img, labs))
            saved += 1
    finally:
        gz.terminate()
        try:
            gz.wait(10)
        except subprocess.TimeoutExpired:
            gz.kill()
        subprocess.run(["pkill", "-f", wpath])
        log.close()
    print("[ground] layout %d (%s, seed %d, fence %s, supersample %d%s): %d frames in %.0f s, faults %s, boxes %s" % (
        li, split, seed, gen_world.FENCE_LOOK, args.supersample, ", width %d" % W if SCALE != 1 else "", saved, time.time() - t0,
        [ft["type"] for ft in cfg["faults"]], dict(zip(CLASSES, counts))), flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.expanduser("~/querra-data/ground_yolo"))
    ap.add_argument("--layouts", type=int, default=14)
    ap.add_argument("--val-layouts", type=int, default=2)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--settle", type=int, default=3, help="frames to wait after moving the camera")
    ap.add_argument("--split", choices=("train", "val", "test"), help="force every layout into this split")
    ap.add_argument("--patrol", action="store_true", help="the real forest.json world along the patrol route (test)")
    ap.add_argument("--patrol-seed", type=int, help="with --patrol: a random forest of this seed instead of forest.json")
    ap.add_argument("--focus", choices=("wire_break", "post_down", "branch_short"),
                    help="70%% of the poses near a fault (else 45%%), 70%% of those near this fault type")
    ap.add_argument("--posts-down", default="2-3", help="fallen posts per random layout, as MIN-MAX (default 2-3)")
    ap.add_argument("--preview", type=int, default=0, help="also write the first N frames with boxes drawn")
    ap.add_argument("--fence-look", default="classic",
                    help="the strands: classic (3.6 cm glowing yellow rods, as trained so far) or a real conductor (%s); "
                         "a comma-separated list gives the layouts one look each, in turn" % ", ".join(sorted(gen_world.FENCE_LOOKS)))
    ap.add_argument("--supersample", type=int, default=1, help="render the colour camera K times larger, averaged down")
    ap.add_argument("--width", type=int, default=CAM["width"],
                    help="a camera of the same lens this many pixels wide (default the robot's, %d)" % CAM["width"])
    args = ap.parse_args()
    args.looks = args.fence_look.split(",")
    bad = [x for x in args.looks if x not in gen_world.FENCE_LOOKS]
    if bad:
        ap.error("unknown fence look %s (known: %s)" % (", ".join(bad), ", ".join(sorted(gen_world.FENCE_LOOKS))))
    gen_world.FENCE_LOOK = args.looks[0]
    if args.width != CAM["width"]:
        set_width(args.width)
    args.posts_down = tuple(int(v) for v in args.posts_down.split("-"))
    for d in ("images/train", "images/val", "images/test", "labels/train", "labels/val", "labels/test"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    with open(os.path.join(args.out, "data.yaml"), "w") as fh:
        fh.write("# fence look %s, supersample %d%s\n" % (args.fence_look, args.supersample,
                                                          ", width %d" % W if SCALE != 1 else "") +
                 "path: %s\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n" % args.out +
                 "".join("  %d: %s\n" % (i, c) for i, c in enumerate(CLASSES)))
    if args.patrol:
        run_layout(0, 0, 0, "test", args.out, args)
        return
    for li in range(args.start, args.layouts):
        split = args.split or ("val" if li >= args.layouts - args.val_layouts else "train")
        for _ in range(3):
            try:
                run_layout(li, args.seed + li, args.frames, split, args.out, args)
                break
            except RuntimeError as exc:
                print("[ground] %s, retrying" % exc, flush=True)


if __name__ == "__main__":
    main()
