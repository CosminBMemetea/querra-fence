"""Checks how much room the forest world leaves the ground robot along its route.

For every route point (worlds/forest_meta.json), the free space between the route centre and the nearest tree trunk,
spruce tier, branch, bush, log or rock that reaches into the robot's height band (0.12-1.0 m above the ground), from
the visuals in worlds/forest.sdf. Prints the minimum, the 5th percentile and the median, how many route points the
robot's body (0.36 m half width) would touch, and the tightest places.

  python3 tools/ugv_clearance.py      (after sim/gen_forest.py)
"""
import os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, math, re, collections
sdf = open("worlds/forest.sdf").read()
meta = json.load(open("worlds/forest_meta.json"))
route = meta["route"]
LO, HI = 0.12, 1.0
fp = []   # footprints: ("c", x, y, r, what) circle or ("s", x1, y1, x2, y2, r, what) segment
for pose, geom, mat in re.findall(r'<visual name="v\d+"><pose>([^<]+)</pose><geometry>(.*?)</geometry>(<material>.*?</material>)', sdf):
    px, py, pz, ro, pi, yw = map(float, pose.split())
    if "<ellipsoid>" in geom or "<sphere>" in geom:
        if "<sphere>" in geom:
            r = float(re.search(r"<radius>([^<]+)", geom).group(1)); rx = ry = rz = r
        else:
            rx, ry, rz = map(float, re.search(r"<radii>([^<]+)", geom).group(1).split())
        h = min(max(pz, LO), HI)                       # height in the band closest to the centre
        if abs(h - pz) >= rz: continue
        k = math.sqrt(1 - ((h - pz) / rz) ** 2)
        fp.append(("c", px, py, max(rx, ry) * k, "blob r%.2f z%.2f" % (max(rx, ry), pz)))
    elif "<cylinder>" in geom:
        r = float(re.search(r"<radius>([^<]+)", geom).group(1)); L = float(re.search(r"<length>([^<]+)", geom).group(1))
        if r < 0.03: continue                          # wires
        # axis direction from roll/pitch/yaw (cylinder axis is local z)
        ax = (math.sin(pi) * math.cos(yw), math.sin(pi) * math.sin(yw), math.cos(pi)) if ro == 0 else (0, -math.sin(ro), math.cos(ro))
        a = (px - ax[0] * L / 2, py - ax[1] * L / 2, pz - ax[2] * L / 2); b = (px + ax[0] * L / 2, py + ax[1] * L / 2, pz + ax[2] * L / 2)
        # clip the axis to the height band
        if abs(b[2] - a[2]) < 1e-6:
            if not (LO - r <= a[2] <= HI + r): continue
            t0, t1 = 0.0, 1.0
        else:
            t0 = (LO - r - a[2]) / (b[2] - a[2]); t1 = (HI + r - a[2]) / (b[2] - a[2])
            t0, t1 = max(0.0, min(t0, t1)), min(1.0, max(t0, t1))
            if t0 > t1: continue
        p0 = [a[i] + (b[i] - a[i]) * t0 for i in range(3)]; p1 = [a[i] + (b[i] - a[i]) * t1 for i in range(3)]
        fp.append(("s", p0[0], p0[1], p1[0], p1[1], r, "rod r%.2f L%.1f" % (r, L)))
grid = collections.defaultdict(list)
for f in fp:
    xs = (f[1], f[3]) if f[0] == "s" else (f[1],); ys = (f[2], f[4]) if f[0] == "s" else (f[2],)
    for gx in range(int(min(xs) // 5) - 1, int(max(xs) // 5) + 2):
        for gy in range(int(min(ys) // 5) - 1, int(max(ys) // 5) + 2):
            grid[(gx, gy)].append(f)
def clearance(x, y):
    best, what = 99.0, ""
    for f in grid[(int(x // 5), int(y // 5))]:
        if f[0] == "c":
            d = math.hypot(f[1] - x, f[2] - y) - f[3]
        else:
            x1, y1, x2, y2, r = f[1:6]; dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy or 1e-12
            t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L2)); d = math.hypot(x - x1 - t * dx, y - y1 - t * dy) - r
        if d < best: best, what = d, f[-1]
    return best, what
cl = [clearance(x, y) for x, y in route]
vals = sorted(c[0] for c in cl)
print("free space beside the route centre (0.12-1.0 m high): min %.2f m, 5%% %.2f m, median %.2f m" % (vals[0], vals[len(vals) // 20], vals[len(vals) // 2]))
print("route points where the robot body (0.36 m half width) would touch: %d; tighter than 0.8 m: %d of %d" % (sum(v < 0.36 for v in vals), sum(v < 0.8 for v in vals), len(vals)))
for i in sorted(range(len(cl)), key=lambda i: cl[i][0])[:6]:
    print("  route[%d] (%.0f m): %.2f m to %s" % (i, i * 0.5, cl[i][0], cl[i][1]))
