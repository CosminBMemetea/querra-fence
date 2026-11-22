"""Forest enclosure world for the ground robot (UGV): forest.json -> worlds/forest.sdf, worlds/forest_meta.json and
models/querra_ugv/model.sdf.

A fenced woodland paddock (deer park, zoo enclosure) with the same electric fence and fault shapes as the pasture
(sim/geo.py Fence, sim/gen_world.py build_fence). Outside the fence a cleared strip carries the robot's patrol route;
the forest around it is dense, with a few pinch points, logs and rocks next to the route, and crowns over it where
GPS degrades. One fence edge borders an open meadow (open sky).

worlds/forest_meta.json is what the rest of the UGV chain reads: the route (in world coordinates), the spawn pose, the
robot's sensor mounts, the tree crowns (tools/ugv_relay.py turns them into GPS degradation) and the faults with their
positions (for scoring a patrol).

Standard library only (runs with the Gazebo pixi Python or any python3).
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402
from gen_world import Visuals, mat, build_fence, BARK, LEAF_RICH, FIR  # noqa: E402

CFG = os.path.join(geo.ROOT, "forest.json")
OUT = os.path.join(geo.ROOT, "worlds", "forest.sdf")
META = os.path.join(geo.ROOT, "worlds", "forest_meta.json")
GROUND_OBJ = os.path.join(geo.ROOT, "models", "forest_ground", "meshes", "ground.obj")
ROBOT_SDF = os.path.join(geo.ROOT, "models", "querra_ugv", "model.sdf")

# The robot: one place for the geometry and sensor mounts, used for the model SDF and for the meta file (TF tree).
ROBOT = {
    "name": "querra_ugv",
    "base_z": 0.28,                                  # base_link origin above the ground (chassis centre)
    "chassis": [0.80, 0.50, 0.22], "mass_kg": 30.0,
    "wheel_radius": 0.16, "wheel_width": 0.10, "wheel_x": 0.27, "wheel_y": 0.31, "wheel_mass_kg": 2.5,
    # Skid steer slips sideways when it turns, so the track it really turns about is wider than the wheels:
    # calibrated in simulation (tools/ugv_calibrate.py) like a real skid-steer's wheel_separation_multiplier.
    "effective_track_m": 0.62,
    # tyre friction: along the rolling direction (fdir1) and sideways; lower sideways friction lets a skid steer turn
    "wheel_mu": 1.0, "wheel_mu2": 0.35,
    "lidar": {"xyz": [0.12, 0.0, 0.52], "rpy": [0, 0, 0], "hz": 10, "h_samples": 900, "v_samples": 16,
              "v_min_deg": -15.0, "v_max_deg": 15.0, "range_min": 0.3, "range_max": 40.0, "noise_m": 0.01},
    # looks left, at the fence, 6 degrees down
    "camera": {"xyz": [0.0, 0.22, 0.42], "rpy": [0, 0.10, 1.5708], "hz": 10, "width": 640, "height": 400,
               "hfov_deg": 100.0},
    "imu": {"xyz": [0.0, 0.0, 0.0], "rpy": [0, 0, 0], "hz": 100},
}
TOPICS = {"cmd_vel": "/ugv/cmd_vel", "odom": "/ugv/odom", "ground_truth": "/ugv/ground_truth",
          "lidar": "/ugv/lidar", "camera": "/ugv/camera", "imu": "/ugv/imu"}

BARK_DARK = mat(0.25, 0.19, 0.14)
LOG = mat(0.36, 0.27, 0.19)
ROCK = [mat(0.45, 0.44, 0.42), mat(0.38, 0.37, 0.35), mat(0.52, 0.50, 0.46)]
BUSH = [mat(0.15, 0.30, 0.10), mat(0.20, 0.34, 0.12), mat(0.12, 0.25, 0.09)]


def f3(v):
    return " ".join("%.4f" % x for x in v)


class Solids:
    """Collision shapes for the static forest (trunks, posts, logs, rocks): what the robot can bump into."""
    def __init__(self):
        self.items, self.n = [], 0

    def _add(self, geom, pose):
        self.n += 1
        self.items.append('<collision name="c%d"><pose>%s</pose><geometry>%s</geometry></collision>' % (self.n, f3(pose), geom))

    def cyl(self, r, length, pose):
        self._add("<cylinder><radius>%.3f</radius><length>%.3f</length></cylinder>" % (r, length), pose)

    def box(self, size, pose):
        self._add("<box><size>%.3f %.3f %.3f</size></box>" % tuple(size), pose)

    def xml(self):
        return "\n".join(self.items)


def offset_polygon(fence, d):
    """The fence polygon pushed d metres outward (mitred corners; the fence polygon is convex)."""
    poly, n = fence.poly, len(fence.poly)
    normals = []
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        normals.append(fence.outward(bx - ax, by - ay))
    out = []
    for i in range(n):
        n1, n2 = normals[i - 1], normals[i]
        k = d / (1.0 + n1[0] * n2[0] + n1[1] * n2[1])
        out.append((poly[i][0] + (n1[0] + n2[0]) * k, poly[i][1] + (n1[1] + n2[1]) * k))
    return out


def sample_loop(poly, step, start_s):
    """Points every `step` metres around a closed polygon, starting `start_s` metres along it and ending there."""
    n = len(poly)
    edges, total = [], 0.0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        edges.append((a, b, total, L))
        total += L

    def at(s):
        s %= total
        for a, b, s0, L in edges:
            if s <= s0 + L:
                t = (s - s0) / L
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return poly[0]
    k = int(total / step)
    return [at(start_s + i * total / k) for i in range(k + 1)], total


def dist_to_path(path, x, y):
    best = 1e18
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def nearest_edge(poly, x, y):
    best, idx = 1e18, 0
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        d = math.hypot(x - ax - t * dx, y - ay - t * dy)
        if d < best:
            best, idx = d, i
    return idx


class Grid:
    """Spatial hash for "is anything solid near here" checks while placing trees and obstacles."""
    def __init__(self, cell=4.0):
        self.cell, self.g = cell, {}

    def add(self, x, y, r):
        self.g.setdefault((int(x // self.cell), int(y // self.cell)), []).append((x, y, r))

    def clear(self, x, y, r, gap):
        cx, cy = int(x // self.cell), int(y // self.cell)
        for i in range(cx - 2, cx + 3):
            for j in range(cy - 2, cy + 3):
                for (px, py, pr) in self.g.get((i, j), ()):
                    if math.hypot(px - x, py - y) < r + pr + gap:
                        return False
        return True


def broadleaf(v, s, x, y, rnd, crowns):
    """Forest broadleaf: a tall bare trunk and a high crown of a few blobs."""
    r_t = rnd.uniform(0.14, 0.32)
    hb = rnd.uniform(3.5, 6.5)                       # crown base
    v.cyl(r_t, hb + 1.2, (x, y, (hb + 1.2) / 2, 0, 0, 0), BARK if rnd.random() < 0.6 else BARK_DARK)
    s.cyl(r_t, 3.0, (x, y, 1.5, 0, 0, 0))
    r = rnd.uniform(3.0, 4.6)
    v.ellipsoid((r, r, r * 0.75), (x, y, hb + r * 0.6, 0, 0, 0), rnd.choice(LEAF_RICH))
    for _ in range(rnd.randint(1, 2)):
        a, k = rnd.uniform(0, 2 * math.pi), rnd.uniform(0.4, 0.7)
        rr = r * rnd.uniform(0.55, 0.75)
        v.ellipsoid((rr, rr, rr * 0.8), (x + math.cos(a) * r * k, y + math.sin(a) * r * k, hb + r * rnd.uniform(0.7, 1.1), 0, 0, 0),
                    rnd.choice(LEAF_RICH))
    crowns.append((round(x, 2), round(y, 2), round(r * 1.1, 2), round(hb + r * 0.6, 2)))
    return r_t


def fir(v, s, x, y, rnd, crowns):
    """Spruce: a trunk and stacked tiers, the lowest branches about 1.3-1.9 m up (trimmed, as along a kept fence
    strip; untrimmed spruce branches hang at robot height and block the strip), the top at 10-14 m."""
    k = rnd.uniform(0.9, 1.25)
    r_t = 0.16 * k
    v.cyl(r_t, 2.7 * k, (x, y, 1.35 * k, 0, 0, 0), BARK_DARK)
    s.cyl(r_t, 2.7 * k, (x, y, 1.35 * k, 0, 0, 0))
    m = rnd.choice(FIR)
    z = 1.8 * k
    for i, (r, hh) in enumerate(((2.0, 1.6), (1.7, 1.5), (1.35, 1.4), (1.0, 1.3), (0.6, 1.1))):
        v.ellipsoid((r * k, r * k, hh * k), (x, y, z + hh * k * 0.8, 0, 0, 0), m if i % 2 == 0 else rnd.choice(FIR))
        z += hh * k * 1.05
    crowns.append((round(x, 2), round(y, 2), round(2.0 * k, 2), round(z * 0.55, 2)))
    return r_t


def write_ground(path, cx, cy, half=320.0, tile_m=6.0):
    xs, ys = (cx - half, cx + half), (cy - half, cy + half)
    out = ["# GENERATED by sim/gen_forest.py: flat forest floor, UVs tile every %.0f m" % tile_m]
    for y in ys:
        for x in xs:
            out.append("v %.2f %.2f 0.000" % (x, y))
    for y in ys:
        for x in xs:
            out.append("vt %.4f %.4f" % (x / tile_m, y / tile_m))
    out += ["vn 0 0 1", "f 1/1/1 2/2/1 4/4/1", "f 1/1/1 4/4/1 3/3/1"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def build_forest(cfg, fence, route):
    fc = cfg["forest"]
    rnd = random.Random(cfg.get("seed", 1))
    v, s = Visuals(), Solids()
    crowns, grid = [], Grid()
    poly = fence.poly
    meadow = set(fc.get("meadow_edges", []))
    corridor, band, clear = fc["corridor_m"], fc["band_m"], fc["fence_clear_m"]
    for p in fence.posts:                                # posts are solid: keep trees off them
        grid.add(p["x"], p["y"], 0.3)
    stats = dict(trees=0, firs=0, pinch=0, logs=0, rocks=0, bushes=0)

    def place_tree(x, y, pinch=False):
        if not grid.clear(x, y, 0.35, 1.2 if not pinch else 0.4):
            return False
        # spruce tiers reach about 2 m out: keep spruces back from the route so they do not overhang the strip
        is_fir = (rnd.random() < fc["fir_share"] and not pinch
                  and (geo.inside(poly, x, y) or dist_to_path(route, x, y) >= fc.get("fir_corridor_m", 2.2)))
        r_t = (fir if is_fir else broadleaf)(v, s, x, y, rnd, crowns)
        grid.add(x, y, r_t)
        stats["trees"] += 1
        stats["firs"] += is_fir
        return True

    # pinch points first: a trunk close to the route on the side away from the fence
    idx = sorted(rnd.sample(range(40, len(route) - 40), fc["pinch_points"]))
    for i in idx:
        (ax, ay), (bx, by) = route[i - 1], route[i + 1]
        L = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = fence.outward(bx - ax, by - ay)      # away from the fence
        d = rnd.uniform(1.25, 1.4)
        if place_tree(route[i][0] + nx * d, route[i][1] + ny * d, pinch=True):
            stats["pinch"] += 1

    # the forest: a jittered grid in a band around the fence
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    sp = fc["tree_spacing_m"]
    x = min(xs) - band
    while x < max(xs) + band:
        y = min(ys) - band
        while y < max(ys) + band:
            tx, ty = x + rnd.uniform(-0.45, 0.45) * sp, y + rnd.uniform(-0.45, 0.45) * sp
            y += sp
            d_f = geo.dist_to_polyline(poly, tx, ty)[0]
            if d_f > band or d_f < clear:
                continue
            if nearest_edge(poly, tx, ty) in meadow:      # a clearing on both sides of that fence edge
                continue
            if not geo.inside(poly, tx, ty) and dist_to_path(route, tx, ty) < corridor:
                continue
            place_tree(tx, ty)
        x += sp

    # logs lying next to the route (outer side), roughly along it
    for i in sorted(rnd.sample(range(30, len(route) - 30), fc["logs"])):
        (ax, ay), (bx, by) = route[i - 1], route[i + 1]
        hd = math.atan2(by - ay, bx - ax) + rnd.uniform(-0.35, 0.35)
        nx, ny = fence.outward(bx - ax, by - ay)
        r, L = rnd.uniform(0.12, 0.22), rnd.uniform(2.5, 4.5)
        cx, cy = route[i][0] + nx * rnd.uniform(1.45, 1.8), route[i][1] + ny * rnd.uniform(1.45, 1.8)
        ends = [(cx + math.cos(hd) * L / 2, cy + math.sin(hd) * L / 2), (cx - math.cos(hd) * L / 2, cy - math.sin(hd) * L / 2)]
        if min(dist_to_path(route, ex, ey) for ex, ey in ends) < 1.0 or not grid.clear(cx, cy, L / 2, 0.2):
            continue
        pose = (cx, cy, r * 0.9, 0, math.pi / 2, hd)
        v.cyl(r, L, pose, LOG)
        s.cyl(r, L, pose)
        grid.add(cx, cy, L / 2)
        stats["logs"] += 1

    # rocks between the route and the fence, or on the outer side
    for i in sorted(rnd.sample(range(20, len(route) - 20), fc["rocks"])):
        (ax, ay), (bx, by) = route[i - 1], route[i + 1]
        nx, ny = fence.outward(bx - ax, by - ay)
        side = rnd.choice((-1, 1))
        d = rnd.uniform(1.05, 1.5) if side > 0 else rnd.uniform(0.95, 1.2)   # fence side: the fence is 1.9 m away
        cx, cy = route[i][0] + nx * d * side, route[i][1] + ny * d * side
        rx, ry, rz = rnd.uniform(0.3, 0.55), rnd.uniform(0.25, 0.45), rnd.uniform(0.2, 0.38)
        if not grid.clear(cx, cy, max(rx, ry), 0.2):
            continue
        yaw = rnd.uniform(0, math.pi)
        v.ellipsoid((rx, ry, rz), (cx, cy, rz * 0.45, 0, 0, yaw), rnd.choice(ROCK))
        s.box((rx * 1.5, ry * 1.5, rz * 1.4), (cx, cy, rz * 0.45, 0, 0, yaw))
        grid.add(cx, cy, max(rx, ry))
        stats["rocks"] += 1

    # undergrowth (no collision; the LiDAR still sees it), kept off the route
    for _ in range(4000):
        if stats["bushes"] >= 260:
            break
        p = fence.posts[rnd.randrange(len(fence.posts))]
        side = rnd.choice((-1, 1))
        d = rnd.uniform(0.5, band)
        bx, by = p["x"] + p["out"][0] * d * side + rnd.uniform(-2, 2), p["y"] + p["out"][1] * d * side + rnd.uniform(-2, 2)
        if dist_to_path(route, bx, by) < 1.5 or geo.dist_to_polyline(poly, bx, by)[0] < 0.5:
            continue
        r = rnd.uniform(0.35, 0.8)
        v.ellipsoid((r, r * rnd.uniform(0.8, 1.2), r * 0.7), (bx, by, r * 0.45, 0, 0, rnd.uniform(0, 3)), rnd.choice(BUSH), shadows=False)
        stats["bushes"] += 1

    # fallen branches on the fence (branch_short): from a tree outside, across the wires, over the route
    for ft in cfg["faults"]:
        if ft["type"] != "branch_short":
            continue
        ax, ay, _ = fence.fault_anchor(ft)
        ox, oy = fence.fault_out(ft)
        tx, ty = ax + ox * 4.6, ay + oy * 4.6
        broadleaf(v, s, tx, ty, rnd, crowns)
        start = (tx - ox * 0.3, ty - oy * 0.3, 3.4)
        end = (ax - ox * 2.0, ay - oy * 2.0, 0.05)
        v.rod(start, end, 0.12, BARK, shadows=True)
        for f in (0.5, 0.75, 0.93):
            p = [start[i] + (end[i] - start[i]) * f for i in range(3)]
            v.sphere(0.7, (p[0], p[1], p[2] + 0.35, 0, 0, 0), rnd.choice(LEAF_RICH))
    return v, s, crowns, stats


def post_solids(fence):
    s = Solids()
    for p in fence.posts:
        h = 1.35 if p["corner"] else 1.2
        r = 0.075 if p["corner"] else 0.05
        if p["tilt"] == 0.0:
            s.cyl(r, h, (p["x"], p["y"], h / 2, 0, 0, 0))
    return s


def pose_xml(m):
    return f3(m["xyz"] + m["rpy"])


def noise(sd):
    return '<noise type="gaussian"><mean>0</mean><stddev>%g</stddev></noise>' % sd


def robot_sdf():
    R = ROBOT
    cl, cw, ch = R["chassis"]
    m = R["mass_kg"]
    li, ca, im = R["lidar"], R["camera"], R["imu"]
    wr, ww, wm = R["wheel_radius"], R["wheel_width"], R["wheel_mass_kg"]
    wheels = []
    for name, sx, sy in (("fl", 1, 1), ("fr", 1, -1), ("rl", -1, 1), ("rr", -1, -1)):
        wheels.append("""    <link name="wheel_{n}">
      <pose>{x:.3f} {y:.3f} {z:.3f} 0 0 0</pose>
      <inertial><mass>{wm}</mass><inertia><ixx>{io:.4f}</ixx><ixy>0</ixy><ixz>0</ixz><iyy>{ia:.4f}</iyy><iyz>0</iyz><izz>{io:.4f}</izz></inertia></inertial>
      <visual name="tyre"><pose>0 0 0 1.5708 0 0</pose><geometry><cylinder><radius>{wr}</radius><length>{ww}</length></cylinder></geometry>
        <material><ambient>0.08 0.08 0.08 1</ambient><diffuse>0.08 0.08 0.08 1</diffuse></material></visual>
      <visual name="hub"><pose>0 {hy:.3f} 0 1.5708 0 0</pose><geometry><cylinder><radius>{hr:.3f}</radius><length>0.01</length></cylinder></geometry>
        <material><ambient>0.6 0.6 0.62 1</ambient><diffuse>0.6 0.6 0.62 1</diffuse></material></visual>
      <collision name="tyre"><pose>0 0 0 1.5708 0 0</pose><geometry><cylinder><radius>{wr}</radius><length>{ww}</length></cylinder></geometry>
        <surface><friction><ode><mu>{mu}</mu><mu2>{mu2}</mu2><fdir1>1 0 0</fdir1></ode></friction></surface></collision>
    </link>
    <joint name="wheel_{n}_joint" type="revolute"><parent>base_link</parent><child>wheel_{n}</child>
      <axis><xyz>0 1 0</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit><dynamics><damping>0.05</damping></dynamics></axis></joint>""".format(
            n=name, x=sx * R["wheel_x"], y=sy * R["wheel_y"], z=wr, wm=wm, wr=wr, ww=ww,
            io=wm * (3 * wr * wr + ww * ww) / 12, ia=wm * wr * wr / 2, hy=sy * (ww / 2 + 0.003), hr=wr * 0.45,
            mu=R["wheel_mu"], mu2=R["wheel_mu2"]))
    imu_noise = "".join("<%s>%s</%s>" % (a, noise(0.003), a) for a in "xyz")
    acc_noise = "".join("<%s>%s</%s>" % (a, noise(0.03), a) for a in "xyz")
    return """<?xml version="1.0"?>
<!-- GENERATED by sim/gen_forest.py (ROBOT). Do not edit by hand. -->
<sdf version="1.9">
  <model name="{name}">
    <link name="base_link">
      <pose>0 0 {bz} 0 0 0</pose>
      <inertial><mass>{m}</mass><inertia><ixx>{ixx:.3f}</ixx><ixy>0</ixy><ixz>0</ixz><iyy>{iyy:.3f}</iyy><iyz>0</iyz><izz>{izz:.3f}</izz></inertia></inertial>
      <visual name="chassis"><geometry><box><size>{cl} {cw} {ch}</size></box></geometry>
        <material><ambient>0.20 0.30 0.18 1</ambient><diffuse>0.20 0.30 0.18 1</diffuse><specular>0.1 0.1 0.1 1</specular></material></visual>
      <visual name="deck"><pose>0 0 {dz:.3f} 0 0 0</pose><geometry><box><size>{dl:.3f} {dw:.3f} 0.02</size></box></geometry>
        <material><ambient>0.12 0.12 0.12 1</ambient><diffuse>0.12 0.12 0.12 1</diffuse></material></visual>
      <visual name="mast"><pose>{lx:.3f} {ly:.3f} {mz:.3f} 0 0 0</pose><geometry><cylinder><radius>0.025</radius><length>{ml:.3f}</length></cylinder></geometry>
        <material><ambient>0.3 0.3 0.3 1</ambient><diffuse>0.3 0.3 0.3 1</diffuse></material></visual>
      <visual name="lidar_body"><pose>{lx:.3f} {ly:.3f} {lz:.3f} 0 0 0</pose><geometry><cylinder><radius>0.05</radius><length>0.07</length></cylinder></geometry>
        <material><ambient>0.05 0.05 0.05 1</ambient><diffuse>0.05 0.05 0.05 1</diffuse></material></visual>
      <visual name="camera_body"><pose>{cx:.3f} {cy:.3f} {cz:.3f} 0 0 0</pose><geometry><box><size>0.06 0.06 0.05</size></box></geometry>
        <material><ambient>0.05 0.05 0.05 1</ambient><diffuse>0.05 0.05 0.05 1</diffuse></material></visual>
      <visual name="beacon"><pose>-0.32 0 {bcz:.3f} 0 0 0</pose><geometry><sphere><radius>0.03</radius></sphere></geometry>
        <material><ambient>1 0.5 0 1</ambient><diffuse>1 0.5 0 1</diffuse><emissive>1 0.45 0 1</emissive></material></visual>
      <collision name="chassis"><geometry><box><size>{cl} {cw} {ch}</size></box></geometry></collision>
      <sensor name="lidar" type="gpu_lidar">
        <pose>{lidar_pose}</pose>
        <topic>{t_lidar}</topic>
        <gz_frame_id>ugv_lidar</gz_frame_id>
        <update_rate>{lhz}</update_rate><always_on>1</always_on><visualize>false</visualize>
        <lidar>
          <scan>
            <horizontal><samples>{hs}</samples><resolution>1</resolution><min_angle>{hmin:.6f}</min_angle><max_angle>{hmax:.6f}</max_angle></horizontal>
            <vertical><samples>{vs}</samples><resolution>1</resolution><min_angle>{vmin:.6f}</min_angle><max_angle>{vmax:.6f}</max_angle></vertical>
          </scan>
          <range><min>{rmin}</min><max>{rmax}</max><resolution>0.01</resolution></range>
          <noise><type>gaussian</type><mean>0</mean><stddev>{lnoise}</stddev></noise>
        </lidar>
      </sensor>
      <sensor name="camera" type="camera">
        <pose>{cam_pose}</pose>
        <topic>{t_cam}</topic>
        <update_rate>{chz}</update_rate><always_on>1</always_on><visualize>false</visualize>
        <camera><horizontal_fov>{hfov:.4f}</horizontal_fov><image><width>{w}</width><height>{h}</height></image>
          <clip><near>0.1</near><far>80</far></clip></camera>
      </sensor>
      <sensor name="imu" type="imu">
        <pose>{imu_pose}</pose>
        <topic>{t_imu}</topic>
        <update_rate>{ihz}</update_rate><always_on>1</always_on>
        <imu><angular_velocity>{imu_noise}</angular_velocity><linear_acceleration>{acc_noise}</linear_acceleration></imu>
      </sensor>
    </link>
{wheels}
    <plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
      <left_joint>wheel_fl_joint</left_joint><left_joint>wheel_rl_joint</left_joint>
      <right_joint>wheel_fr_joint</right_joint><right_joint>wheel_rr_joint</right_joint>
      <wheel_separation>{track}</wheel_separation>
      <wheel_radius>{wr}</wheel_radius>
      <topic>{t_cmd}</topic>
      <odom_topic>{t_odom}</odom_topic>
      <tf_topic>/ugv/tf</tf_topic>
      <frame_id>ugv_odom</frame_id>
      <child_frame_id>ugv_base_link</child_frame_id>
      <odom_publish_frequency>30</odom_publish_frequency>
      <max_linear_velocity>1.2</max_linear_velocity><min_linear_velocity>-0.6</min_linear_velocity>
      <max_angular_velocity>1.2</max_angular_velocity><min_angular_velocity>-1.2</min_angular_velocity>
      <max_linear_acceleration>1.0</max_linear_acceleration><min_linear_acceleration>-1.5</min_linear_acceleration>
      <max_angular_acceleration>2.5</max_angular_acceleration><min_angular_acceleration>-2.5</min_angular_acceleration>
    </plugin>
    <plugin filename="gz-sim-odometry-publisher-system" name="gz::sim::systems::OdometryPublisher">
      <odom_frame>world</odom_frame>
      <robot_base_frame>ugv_base_link</robot_base_frame>
      <odom_topic>{t_truth}</odom_topic>
      <tf_topic>/ugv/ground_truth/tf</tf_topic>
      <odom_publish_frequency>20</odom_publish_frequency>
      <dimensions>3</dimensions>
    </plugin>
  </model>
</sdf>
""".format(
        name=R["name"], bz=R["base_z"], m=m, cl=cl, cw=cw, ch=ch,
        ixx=m * (ch * ch + cw * cw) / 12, iyy=m * (ch * ch + cl * cl) / 12, izz=m * (cw * cw + cl * cl) / 12,
        dz=ch / 2 + 0.01, dl=cl * 0.9, dw=cw * 0.9,
        lx=li["xyz"][0], ly=li["xyz"][1], lz=li["xyz"][2] - 0.035, mz=(ch / 2 + li["xyz"][2] - 0.07) / 2, ml=li["xyz"][2] - 0.07 - ch / 2,
        cx=ca["xyz"][0], cy=ca["xyz"][1] - 0.03, cz=ca["xyz"][2], bcz=ch / 2 + 0.03,
        lidar_pose=pose_xml(li), t_lidar=TOPICS["lidar"], lhz=li["hz"], hs=li["h_samples"],
        hmin=-math.pi, hmax=math.pi - 2 * math.pi / li["h_samples"], vs=li["v_samples"],
        vmin=math.radians(li["v_min_deg"]), vmax=math.radians(li["v_max_deg"]), rmin=li["range_min"], rmax=li["range_max"],
        lnoise=li["noise_m"], cam_pose=pose_xml(ca), t_cam=TOPICS["camera"], chz=ca["hz"], hfov=math.radians(ca["hfov_deg"]),
        w=ca["width"], h=ca["height"], imu_pose=pose_xml(im), t_imu=TOPICS["imu"], ihz=im["hz"],
        imu_noise=imu_noise, acc_noise=acc_noise, wheels="\n".join(wheels), track=R["effective_track_m"], wr=wr,
        t_cmd=TOPICS["cmd_vel"], t_odom=TOPICS["odom"], t_truth=TOPICS["ground_truth"])


SYSTEMS = """    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>"""

SCENE = """    <scene>
      <grid>false</grid>
      <ambient>0.40 0.42 0.44 1</ambient>
      <background>0.62 0.76 0.90 1</background>
      <shadows>true</shadows>
      <sky></sky>
    </scene>
    <light name="sun" type="directional">
      <pose>0 0 300 0 0 0</pose>
      <cast_shadows>true</cast_shadows>
      <intensity>1.15</intensity>
      <direction>0.45 0.35 -0.82</direction>
      <diffuse>1.0 0.93 0.82 1</diffuse>
      <specular>0.2 0.2 0.18 1</specular>
    </light>
    <light name="sky_fill" type="directional">
      <cast_shadows>false</cast_shadows>
      <intensity>0.3</intensity>
      <direction>-0.4 -0.5 -0.75</direction>
      <diffuse>0.60 0.70 0.85 1</diffuse>
      <specular>0 0 0 1</specular>
    </light>"""

GROUND = """    <model name="forest_floor">
      <static>true</static>
      <link name="link">
        <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry>
          <surface><friction><ode><mu>0.9</mu><mu2>0.9</mu2></ode></friction></surface></collision>
        <visual name="visual">
          <cast_shadows>false</cast_shadows>
          <geometry><mesh><uri>model://forest_ground/meshes/ground.obj</uri></mesh></geometry>
          <material>
            <ambient>1 1 1 1</ambient><diffuse>0.62 0.52 0.38 1</diffuse><specular>0.03 0.03 0.03 1</specular>
            <pbr><metal>
              <albedo_map>model://pasture_ground/materials/textures/grass_albedo.png</albedo_map>
              <normal_map>model://pasture_ground/materials/textures/grass_normal.png</normal_map>
              <roughness>0.97</roughness><metalness>0.0</metalness>
            </metal></pbr>
          </material>
        </visual>
      </link>
    </model>"""


def main():
    cfg = geo.load_config(CFG)
    fence = geo.Fence(cfg)
    rc = cfg["robot"]
    loop = offset_polygon(fence, rc["offset_outside_m"])
    route, loop_len = sample_loop(loop, rc["route_step_m"], rc["start_s_m"])
    (x0, y0), (x1, y1) = route[0], route[2]
    spawn = (x0, y0, math.atan2(y1 - y0, x1 - x0))
    forest_v, forest_s, crowns, stats = build_forest(cfg, fence, route)
    cx = sum(p[0] for p in fence.poly) / len(fence.poly)
    cy = sum(p[1] for p in fence.poly) / len(fence.poly)
    write_ground(GROUND_OBJ, cx, cy)
    with open(os.path.join(os.path.dirname(os.path.dirname(GROUND_OBJ)), "model.config"), "w") as f:
        f.write('<?xml version="1.0"?>\n<model><name>forest_ground</name><version>1.0</version><sdf version="1.9">model.sdf</sdf>'
                '<description>Flat forest floor mesh (GENERATED by sim/gen_forest.py).</description></model>\n')

    os.makedirs(os.path.dirname(ROBOT_SDF), exist_ok=True)
    with open(ROBOT_SDF, "w") as f:
        f.write(robot_sdf())
    with open(os.path.join(os.path.dirname(ROBOT_SDF), "model.config"), "w") as f:
        f.write('<?xml version="1.0"?>\n<model><name>querra_ugv</name><version>1.0</version><sdf version="1.9">model.sdf</sdf>'
                '<description>QUERRA ground robot: 4x4 skid steer, 16-beam 3D LiDAR, side camera at the fence, IMU '
                '(GENERATED by sim/gen_forest.py).</description></model>\n')

    fence_model = ('<model name="electric_fence"><static>true</static><link name="link">\n%s\n%s\n</link></model>'
                   % (build_fence(fence).xml(), post_solids(fence).xml()))
    forest_model = ('<model name="forest"><static>true</static><link name="link">\n%s\n%s\n</link></model>'
                    % (forest_v.xml(), forest_s.xml()))
    o = cfg["origin"]
    world = """<?xml version="1.0" encoding="UTF-8"?>
<!-- GENERATED by sim/gen_forest.py from forest.json. Do not edit by hand: change forest.json. -->
<sdf version="1.9">
  <world name="forest">
    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
{systems}
    <gravity>0 0 -9.8</gravity>
    <spherical_coordinates>
      <surface_model>EARTH_WGS84</surface_model>
      <world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>{lat}</latitude_deg><longitude_deg>{lon}</longitude_deg><elevation>{alt}</elevation>
    </spherical_coordinates>
{scene}
{ground}
    <include>
      <uri>model://querra_ugv</uri>
      <name>querra_ugv</name>
      <pose>{sx:.3f} {sy:.3f} 0.05 0 0 {syaw:.4f}</pose>
    </include>
{fence}
{forest}
  </world>
</sdf>
""".format(systems=SYSTEMS, lat=o["lat"], lon=o["lon"], alt=o["alt_m"], scene=SCENE, ground=GROUND,
           sx=spawn[0], sy=spawn[1], syaw=spawn[2], fence=fence_model, forest=forest_model)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(world)

    faults = []
    for ft in cfg["faults"]:
        ax, ay, s_along = fence.fault_anchor(ft)
        faults.append(dict(id=ft["id"], type=ft["type"], x=round(ax, 2), y=round(ay, 2), s=round(s_along, 1)))
    meta = {
        "_info": "GENERATED by sim/gen_forest.py from forest.json: what tools/ugv_relay.py and the Jetson's ugv nodes need.",
        "world": "forest", "origin": o, "gps": cfg["gps"], "odom": cfg.get("odom", {}),
        "route": [[round(x, 2), round(y, 2)] for x, y in route], "route_length_m": round(loop_len, 1),
        "spawn": [round(spawn[0], 3), round(spawn[1], 3), round(spawn[2], 4)],
        "speed_ms": rc["speed_ms"], "fence_length_m": round(fence.length, 1), "posts": len(fence.posts),
        "faults": faults, "robot": ROBOT, "topics": TOPICS, "crowns": crowns,
        "fence_posts": [[round(p["x"], 2), round(p["y"], 2)] for p in fence.posts],
    }
    with open(META, "w", encoding="utf-8") as f:
        json.dump(meta, f, separators=(",", ":"))
    print("[gen_forest] %s: %d posts, %.0f m of fence, %d faults; route %.0f m; %d trees (%d firs, %d pinch points), "
          "%d logs, %d rocks, %d bushes" % (os.path.relpath(OUT, geo.ROOT), len(fence.posts), fence.length, len(faults),
                                            loop_len, stats["trees"], stats["firs"], stats["pinch"], stats["logs"],
                                            stats["rocks"], stats["bushes"]))


if __name__ == "__main__":
    main()
