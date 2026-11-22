"""Perspective render of a captured LiDAR cloud (numpy only): OUT_PREFIX.ppm and OUT_PREFIX.json (label anchors).

  python tools/ugv_lidar_render.py CLOUD.npz OUT_PREFIX VIEW
      VIEW back: from ahead of the robot, looking back along the strip it drove
           side: from high up to the side, looking at the middle of the strip

Points are blue by height (lighter = higher, the ground darkest). The band 0.33-1.68 m above the ground, which
pointcloud_to_laserscan keeps as the 2D scan SLAM matches against its map, is orange.
"""
import json, math, sys
import numpy as np

src, out, view = sys.argv[1], sys.argv[2], sys.argv[3]
d = np.load(src)
P, poses = d["pts"].astype(np.float64), d["poses"]
meta = json.load(open("worlds/forest_meta.json"))
OW, OH, SS, FOV = 1600, 900, 2, 58.0
W, H = OW * SS, OH * SS                      # render at 2x, then average 2x2 blocks
BG = np.array([13, 13, 13], float)
SLICE = (0.33, 1.68)                       # the band pointcloud_to_laserscan keeps for SLAM (above the ground)

xs, ys, yaws = poses[:, 1], poses[:, 2], poses[:, 4]
end = np.array([xs[-1], ys[-1]]); hd = np.array([math.cos(yaws[-1]), math.sin(yaws[-1])])
mid = np.array([xs.mean(), ys.mean()])
path_dir = end - np.array([xs[0], ys[0]]); path_dir /= np.linalg.norm(path_dir)
side = np.array([-path_dir[1], path_dir[0]])
if view == "back":                          # ahead of the robot, looking back along the strip it mapped
    C = np.array([*(end + 7.5 * hd + 1.6 * side), 4.0]); T = np.array([*(end - 9.0 * path_dir), 0.6])
else:                                       # high, to the side, looking at the middle of the strip
    C = np.array([*(mid + 20.0 * side - 6.0 * path_dir), 15.0]); T = np.array([*(mid + 1.0 * path_dir), 0.0])
f = T - C; f /= np.linalg.norm(f)
r = np.cross(f, [0, 0, 1.0]); r /= np.linalg.norm(r)
u = np.cross(r, f)
F = (W / 2) / math.tan(math.radians(FOV / 2))


def project(X):
    D = X - C
    xc, yc, zc = D @ r, D @ u, D @ f
    return W / 2 + F * xc / np.maximum(zc, 1e-6), H / 2 - F * yc / np.maximum(zc, 1e-6), zc


px, py, zc = project(P)
z = P[:, 2]
keep = (zc > 1.2) & (px >= -2) & (px < W + 2) & (py >= -2) & (py < H + 2)
px, py, zc, z = px[keep], py[keep], zc[keep], z[keep]

# colour: blue by height (ground darkest), the SLAM slice in orange; fade with distance
def ramp(t, stops):
    t = np.clip(t, 0, 1)[:, None]
    pos = np.linspace(0, 1, len(stops))
    out = np.empty((len(t), 3))
    for k in range(3):
        out[:, k] = np.interp(t[:, 0], pos, [s[k] for s in stops])
    return out

hexc = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
col = ramp(z / 9.0, [hexc("#184f95"), hexc("#2a78d6"), hexc("#6da7ec"), hexc("#cde2fb")])
sl = (z >= SLICE[0]) & (z <= SLICE[1])
col[sl] = hexc("#f08a5a")
gr = z < 0.15                               # the ground: darker, so the trees and the fence stand out
col[gr] = np.array(hexc("#104281")) * 0.75
fog = np.exp(-zc / 55.0)[:, None]
col = BG + (col - BG) * (0.25 + 0.75 * fog)

# splats: 1 px, 2x2 within 14 m; nearest point wins each pixel
cand_x, cand_y, cand_z, cand_c = [px.astype(int)], [py.astype(int)], [zc], [col]
for ox, oy in ((1, 0), (0, 1), (1, 1)):         # 2x2 at 2x resolution = one pixel, placed to the half pixel
    cand_x.append(px.astype(int) + ox); cand_y.append(py.astype(int) + oy)
    cand_z.append(zc); cand_c.append(col)
cx, cy, cz, cc = map(np.concatenate, (cand_x, cand_y, cand_z, cand_c))
ok = (cx >= 0) & (cx < W) & (cy >= 0) & (cy < H)
cx, cy, cz, cc = cx[ok], cy[ok], cz[ok], cc[ok]
idx = cy * W + cx
order = np.argsort(cz, kind="stable")
uniq, first = np.unique(idx[order], return_index=True)
img = np.tile(BG, (H * W, 1))
img[uniq] = cc[order][first]
img = img.reshape(H, W, 3)


def line3d(a, b, color, width=2, n=None):
    n = n or 200
    t = np.linspace(0, 1, n)[:, None]
    X = a + (b - a) * t
    qx, qy, qz = project(X)
    for (x0, y0, z0) in zip(qx, qy, qz):
        if z0 > 1.0:
            for ox in range(width):
                for oy in range(width):
                    xi, yi = int(x0) + ox, int(y0) + oy
                    if 0 <= xi < W and 0 <= yi < H:
                        img[yi, xi] = color

# the path driven (true poses), on the ground
pts = np.stack([xs, ys, np.full_like(xs, 0.04)], 1)
for a, b in zip(pts[:-1], pts[1:]):
    line3d(a, b, np.array([240, 239, 236.0]), 2, 30)

# the robot: a 0.8 x 0.5 x 0.5 m box at the last pose, filled light grey with a dark outline
c, s = math.cos(yaws[-1]), math.sin(yaws[-1])
corners = []
for dx in (-0.4, 0.4):
    for dy in (-0.25, 0.25):
        for dz in (0.05, 0.55):
            corners.append([xs[-1] + c * dx - s * dy, ys[-1] + s * dx + c * dy, dz])
corners = np.array(corners)
qx, qy, qz = project(corners)
hull_pts = sorted(zip(qx, qy))
def cross(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
lower, upper = [], []
for p_ in hull_pts:
    while len(lower) >= 2 and cross(lower[-2], lower[-1], p_) <= 0: lower.pop()
    lower.append(p_)
for p_ in reversed(hull_pts):
    while len(upper) >= 2 and cross(upper[-2], upper[-1], p_) <= 0: upper.pop()
    upper.append(p_)
hull = lower[:-1] + upper[:-1]
x0_, x1_ = int(max(0, min(qx))), int(min(W - 1, max(qx)) + 1)
y0_, y1_ = int(max(0, min(qy))), int(min(H - 1, max(qy)) + 1)
gy, gx = np.mgrid[y0_:y1_, x0_:x1_]
inside = np.ones(gx.shape, bool)
for i in range(len(hull)):
    a, b = hull[i], hull[(i + 1) % len(hull)]
    inside &= ((b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])) >= 0
img[y0_:y1_, x0_:x1_][inside] = (235, 235, 232)
for i in range(len(hull)):
    a, b = hull[i], hull[(i + 1) % len(hull)]
    for t in np.linspace(0, 1, 200):
        xi, yi = int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t)
        if 0 <= xi < W and 0 <= yi < H: img[yi, xi] = (40, 40, 40)

small = img.reshape(OH, SS, OW, SS, 3).mean(axis=(1, 3))
with open(out + ".ppm", "wb") as fh:
    fh.write(b"P6 %d %d 255\n" % (OW, OH)); fh.write(np.clip(small, 0, 255).astype(np.uint8).tobytes())

# label anchors: the robot's top, a fence post, a trunk in the slice, the start of the path
lab = {}
rx, ry, _ = project(np.array([[xs[-1], ys[-1], 0.6]]))
lab["robot"] = [float(rx[0]), float(ry[0])]
sx_, sy_, sz_ = project(np.array([[xs[0], ys[0], 0.04]]))
if sz_[0] > 1 and 0 <= sx_[0] < W and 0 <= sy_[0] < H: lab["start"] = [float(sx_[0]), float(sy_[0])]
posts = np.array(meta["fence_posts"])
cand = []
for x_, y_ in posts:
    qx_, qy_, qz_ = project(np.array([[x_, y_, 1.0]]))
    if 3 < qz_[0] < 25 and 160 < qx_[0] < W - 520 and 240 < qy_[0] < H - 160:
        cand.append((qz_[0], float(qx_[0]), float(qy_[0])))
if cand:
    cand.sort(); lab["post"] = list(cand[len(cand) // 2][1:])
trunks = []
for x_, y_, rr, hh in meta["crowns"]:
    dmin = np.min(np.hypot(xs - x_, ys - y_))
    if 3 < dmin < 9:
        qx_, qy_, qz_ = project(np.array([[x_, y_, 1.0]]))
        if 4 < qz_[0] < 22 and 160 < qx_[0] < W - 520 and 240 < qy_[0] < H - 160:
            trunks.append((qz_[0], float(qx_[0]), float(qy_[0])))
if trunks:
    trunks.sort(); lab["trunk"] = list(trunks[len(trunks) // 3][1:])
lab = {k: [v[0] / SS, v[1] / SS] for k, v in lab.items()}
json.dump({"W": OW, "H": OH, "labels": lab, "metres": float(np.hypot(*(end - [xs[0], ys[0]]))), "scans": int(len(poses))},
          open(out + ".json", "w"))
print(view, "points drawn", int(keep.sum()), lab)
