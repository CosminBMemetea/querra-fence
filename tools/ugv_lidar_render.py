"""Perspective render of a LiDAR cloud (numpy only): OUT_PREFIX.ppm and OUT_PREFIX.json (callouts for the labels).

  python tools/ugv_lidar_render.py CLOUD.npz OUT_PREFIX VIEW
      back     from ahead of the robot, looking back along the strip it drove (a capture while driving)
      side     from high up to the side, looking at the middle of the strip (a capture while driving)
      loop     the whole loop from high above its south side (a sweep: tools/ugv_lidar_sweep.py)
      F1..F5   that fault from the robot's side of the fence, 12 m around it (a sweep)
      single   one scan, as the LiDAR delivers it in 0.1 s, in the densest forest (a sweep)

Points are blue by height (lighter = higher, the ground darkest). The band 0.33-1.68 m above the ground, which
pointcloud_to_laserscan keeps as the 2D scan SLAM matches against its map, is orange.
"""
import json, math, sys
import numpy as np

src, out, view = sys.argv[1], sys.argv[2], sys.argv[3]
d = np.load(src)
P_all, poses, sizes = d["pts"], d["poses"], d["sizes"]
meta = json.load(open("worlds/forest_meta.json"))
OW, OH, SS, FOV = 1600, 900, 2, 58.0
W, H = OW * SS, OH * SS                      # render at 2x, then average 2x2 blocks
BG = np.array([13, 13, 13], float)
SLICE = (0.33, 1.68)                       # the band pointcloud_to_laserscan keeps for SLAM (above the ground)
FAULT_NAMES = {"wire_break": "broken wire", "branch_short": "branch across the wires", "post_down": "fallen post"}
starts = np.concatenate([[0], np.cumsum(sizes)])
scan_pts = lambda i: P_all[starts[i]:starts[i + 1]]
xs, ys, yaws = poses[:, 1], poses[:, 2], poses[:, 4]
route = np.array(meta["route"], float)
fog_m, splat, robot_at, path, note = 55.0, True, len(poses) - 1, np.stack([xs, ys], 1), None
near_clip = 1.2
callouts = []                                 # (anchor 3D point, dx, dy, text, sub)

if view in ("back", "side"):
    P = P_all.astype(np.float64)
    end = np.array([xs[-1], ys[-1]]); hd = np.array([math.cos(yaws[-1]), math.sin(yaws[-1])])
    mid = np.array([xs.mean(), ys.mean()])
    path_dir = end - np.array([xs[0], ys[0]]); path_dir /= np.linalg.norm(path_dir)
    side = np.array([-path_dir[1], path_dir[0]])
    if view == "back":                      # ahead of the robot, looking back along the strip it mapped
        C = np.array([*(end + 7.5 * hd + 1.6 * side), 4.0]); T = np.array([*(end - 9.0 * path_dir), 0.6])
    else:                                   # high, to the side, looking at the middle of the strip
        C = np.array([*(mid + 20.0 * side - 6.0 * path_dir), 15.0]); T = np.array([*(mid + 1.0 * path_dir), 0.0])
elif view == "loop":
    P = P_all[::2].astype(np.float64)       # every second point is plenty from this far
    fp = np.array(meta["fence_posts"], float)
    cx, cy = (fp[:, 0].min() + fp[:, 0].max()) / 2, (fp[:, 1].min() + fp[:, 1].max()) / 2
    C = np.array([cx - 10, fp[:, 1].min() - 118, 112.0]); T = np.array([cx, cy + 2, 0.0])
    fog_m, splat, robot_at, path = 900.0, False, None, route[::4]
    for f in meta["faults"]:
        callouts.append(((f["x"], f["y"], 1.0), 0, -34, f["id"], None))
    sx, sy, _ = meta["spawn"]
    callouts.append(((sx, sy, 0.3), -30, 40, "start", None))
elif view.startswith("F"):
    f = next(f for f in meta["faults"] if f["id"] == view)
    fx, fy = f["x"], f["y"]
    near = [i for i in range(len(poses)) if math.hypot(xs[i] - fx, ys[i] - fy) < 16.0]
    P = np.concatenate([scan_pts(i) for i in near]).astype(np.float64)
    P = P[(np.hypot(P[:, 0] - fx, P[:, 1] - fy) < 12.0) & (P[:, 2] < 8.0)]
    k = int(np.argmin(np.hypot(route[:, 0] - fx, route[:, 1] - fy)))
    r0 = route[k]
    out_dir = (r0 - [fx, fy]) / max(1e-6, np.linalg.norm(r0 - [fx, fy]))   # from the fence towards the route
    along = route[min(k + 1, len(route) - 1)] - route[max(k - 1, 0)]; along /= np.linalg.norm(along)
    C = np.array([*(np.array([fx, fy]) + out_dir * (np.linalg.norm(r0 - [fx, fy]) + 3.0) + along * 3.0), 3.2])
    T = np.array([fx, fy, 0.3])
    near_clip = 4.5                         # no smear from a trunk right next to the camera
    robot_at = None
    path = route[[i for i in range(len(route)) if math.hypot(*(route[i] - [fx, fy])) < 12.0]]
    at = (fx, fy, 0.5)
    if f["type"] == "post_down":            # point at the post on the ground: the low returns (6-40 cm) near the fault
        low = P[(np.hypot(P[:, 0] - fx, P[:, 1] - fy) < 2.5) & (P[:, 2] > 0.06) & (P[:, 2] < 0.4)]
        if len(low) > 50:
            at = tuple(np.median(low, axis=0))
    callouts.append((at, 150, -150, "%s: %s" % (f["id"], FAULT_NAMES.get(f["type"], f["type"])),
                     "%d scans from the route, 12 m around the fault" % len(near)))
    note = ("The simulated wires are 36 mm thick, like wide polytape. A real 2.5 mm steel wire would barely show "
            "in a 16-beam LiDAR.")
else:                                       # single: one scan where the forest is densest
    dens = [sum(1 for c_ in meta["crowns"] if math.hypot(c_[0] - xs[i], c_[1] - ys[i]) < 12) for i in range(len(poses))]
    i0 = int(np.argmax(dens))
    P = scan_pts(i0).astype(np.float64)
    hd = np.array([math.cos(yaws[i0]), math.sin(yaws[i0])]); side = np.array([-hd[1], hd[0]])
    p0 = np.array([xs[i0], ys[i0]])
    C = np.array([*(p0 - 9.0 * hd + 2.0 * side), 6.0]); T = np.array([*(p0 + 7.0 * hd), 0.0])
    robot_at, path = i0, np.zeros((0, 2))
    callouts.append(((xs[i0], ys[i0], 0.6), 110, -60, "one scan: 0.1 s",
                     "%d points, 16 rings" % len(P)))

f_ = T - C; f_ /= np.linalg.norm(f_)
r = np.cross(f_, [0, 0, 1.0]); r /= np.linalg.norm(r)
u = np.cross(r, f_)
F = (W / 2) / math.tan(math.radians(FOV / 2))


def project(X):
    D = X - C
    xc, yc, zc = D @ r, D @ u, D @ f_
    return W / 2 + F * xc / np.maximum(zc, 1e-6), H / 2 - F * yc / np.maximum(zc, 1e-6), zc


px, py, zc = project(P)
z = P[:, 2]
keep = (zc > near_clip) & (px >= -2) & (px < W + 2) & (py >= -2) & (py < H + 2)
px, py, zc, z = px[keep], py[keep], zc[keep], z[keep]


def ramp(t, stops):
    t = np.clip(t, 0, 1)[:, None]
    pos = np.linspace(0, 1, len(stops))
    o = np.empty((len(t), 3))
    for k_ in range(3):
        o[:, k_] = np.interp(t[:, 0], pos, [s_[k_] for s_ in stops])
    return o


hexc = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
col = ramp(z / 9.0, [hexc("#184f95"), hexc("#2a78d6"), hexc("#6da7ec"), hexc("#cde2fb")])
col[(z >= SLICE[0]) & (z <= SLICE[1])] = hexc("#f08a5a")
col[z < 0.15] = np.array(hexc("#104281")) * 0.75   # the ground: darker, so the trees and the fence stand out
fog = np.exp(-zc / fog_m)[:, None]
col = BG + (col - BG) * (0.25 + 0.75 * fog)

# splats: 2x2 at 2x resolution = one output pixel placed to the half pixel; nearest point wins each pixel
cand_x, cand_y, cand_z, cand_c = [px.astype(int)], [py.astype(int)], [zc], [col]
offs = ((1, 0), (0, 1), (1, 1)) if splat else ()
if view == "single":
    offs = tuple((a_, b_) for a_ in range(-1, 3) for b_ in range(-1, 3) if (a_, b_) != (0, 0))   # bigger dots
for ox, oy in offs:
    cand_x.append(px.astype(int) + ox); cand_y.append(py.astype(int) + oy)
    cand_z.append(zc); cand_c.append(col)
cx_, cy_, cz_, cc_ = map(np.concatenate, (cand_x, cand_y, cand_z, cand_c))
ok = (cx_ >= 0) & (cx_ < W) & (cy_ >= 0) & (cy_ < H)
cx_, cy_, cz_, cc_ = cx_[ok], cy_[ok], cz_[ok], cc_[ok]
order = np.argsort(cz_, kind="stable")
uniq, first = np.unique((cy_ * W + cx_)[order], return_index=True)
img = np.tile(BG, (H * W, 1))
img[uniq] = cc_[order][first]
img = img.reshape(H, W, 3)


def line3d(a, b, color, width=2, n=30):
    t = np.linspace(0, 1, n)[:, None]
    qx, qy, qz = project(a + (b - a) * t)
    for (x0, y0, z0) in zip(qx, qy, qz):
        if z0 > 1.0:
            for ox in range(width * SS):
                for oy in range(width * SS):
                    xi, yi = int(x0) + ox, int(y0) + oy
                    if 0 <= xi < W and 0 <= yi < H:
                        img[yi, xi] = color


pts3 = np.concatenate([path, np.full((len(path), 1), 0.04)], 1) if len(path) else np.zeros((0, 3))
for a, b in zip(pts3[:-1], pts3[1:]):
    if np.linalg.norm(b - a) < 6.0:
        line3d(a, b, np.array([240, 239, 236.0]), 1 if view == "loop" else 2)


def cross2(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


if robot_at is not None:                    # the robot: a 0.8 x 0.5 x 0.5 m box, light grey with a dark outline
    c, s = math.cos(yaws[robot_at]), math.sin(yaws[robot_at])
    corners = np.array([[xs[robot_at] + c * dx - s * dy, ys[robot_at] + s * dx + c * dy, dz]
                        for dx in (-0.4, 0.4) for dy in (-0.25, 0.25) for dz in (0.05, 0.55)])
    qx, qy, qz = project(corners)
    hp = sorted(zip(qx, qy))
    lower, upper = [], []
    for p_ in hp:
        while len(lower) >= 2 and cross2(lower[-2], lower[-1], p_) <= 0: lower.pop()
        lower.append(p_)
    for p_ in reversed(hp):
        while len(upper) >= 2 and cross2(upper[-2], upper[-1], p_) <= 0: upper.pop()
        upper.append(p_)
    hull = lower[:-1] + upper[:-1]
    x0_, x1_ = int(max(0, min(qx))), int(min(W - 1, max(qx)) + 1)
    y0_, y1_ = int(max(0, min(qy))), int(min(H - 1, max(qy)) + 1)
    if x1_ > x0_ and y1_ > y0_:
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


def anchor(x, y, zz):
    qx_, qy_, qz_ = project(np.array([[x, y, zz]]))
    if qz_[0] > 1 and 0 <= qx_[0] < W and 0 <= qy_[0] < H:
        return [float(qx_[0]) / SS, float(qy_[0]) / SS]
    return None


if view in ("back", "side"):                # the callouts of the first two pictures (docs/ugv.md)
    metres, n_sc = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0])), len(poses)
    rob = anchor(xs[-1], ys[-1], 0.6)
    post, trunk = None, None
    cand = []
    for x_, y_ in meta["fence_posts"]:
        qx_, qy_, qz_ = project(np.array([[x_, y_, 1.0]]))
        if 3 < qz_[0] < 25 and 160 < qx_[0] < W - 520 and 240 < qy_[0] < H - 160:
            cand.append((qz_[0], float(qx_[0]) / SS, float(qy_[0]) / SS))
    if cand:
        cand.sort(); post = list(cand[len(cand) // 2][1:])
    tr = []
    for x_, y_, rr_, hh_ in meta["crowns"]:
        if 3 < np.min(np.hypot(xs - x_, ys - y_)) < 9:
            qx_, qy_, qz_ = project(np.array([[x_, y_, 1.0]]))
            if 4 < qz_[0] < 22 and 160 < qx_[0] < W - 520 and 240 < qy_[0] < H - 160:
                tr.append((qz_[0], float(qx_[0]) / SS, float(qy_[0]) / SS))
    if tr:
        tr.sort(); trunk = list(tr[len(tr) // 3][1:])
    st0 = anchor(xs[0], ys[0], 0.04)
    if view == "back":
        lab = [(rob, 90, -40, "the robot", "16-beam LiDAR, 0.52 m up"), (post, 70, 250, "fence: posts and wires", None),
               (trunk, 40, 170, "tree trunk", None), (st0, -210, -40, "path driven", "%.0f m, %d scans" % (metres, n_sc))]
    else:
        lab = [(rob, 60, -70, "the robot", None), (post, 120, -110, "fence: posts and wires", None),
               (trunk, 120, 60, "tree trunk", None)]
else:
    lab = [(anchor(*p3), dx, dy, t_, s_) for p3, dx, dy, t_, s_ in callouts]
lab = [{"at": a_, "dx": dx, "dy": dy, "text": t_, "sub": s_} for a_, dx, dy, t_, s_ in lab if a_ is not None]
json.dump({"W": OW, "H": OH, "view": view, "callouts": lab, "note": note, "scans": int(len(poses))},
          open(out + ".json", "w"))
print(view, "points drawn", int(keep.sum()), "callouts", [c_["text"] for c_ in lab])
