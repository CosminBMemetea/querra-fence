#!/usr/bin/env python3
"""The ground robot's SLAM map against the true forest (numpy; run with Gazebo's Python, which has it).

  python tools/ugv_slam_map.py GRID.npz ROUTE.json OUT.svg

GRID.npz: slam_toolbox's occupancy grid (/map) as saved by tools/ugv_slam_map.sh: "grid" (int8, -1 unknown, 0-100),
"res", "ox", "oy" (its origin in the map frame). The map frame ugv_slam_map starts at the spawn pose, so it is placed in
the world through forest_meta.json "spawn". ROUTE.json: the taught route (ugv_patrol's forest.route.json, world frame).

Draws the whole map with the true trunk positions and the taught route on top, plus two close-ups (the start, where
the teach run closed its loop, and the far side of the loop), and measures how far each true trunk centre is from the
nearest occupied cell (for a perfect map, about the trunk's radius, 0.14-0.32 m).
"""
import base64
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = 'font-family="system-ui, -apple-system, Segoe UI, sans-serif"'
INK, INK2, PAPER = "#0b0b0b", "#52514e", "#e9e6dc"
ROUTE_C, TRUNK_C, POST_C = "#2a78d6", "#eb6834", "#a8803c"


def png_rgba(a):
    """Encode an (h, w, 4) uint8 array as PNG (row 0 first)."""
    h, w, _ = a.shape
    raw = b"".join(b"\x00" + a[i].tobytes() for i in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def grid_png(g, step):
    """Occupied black, seen-free white, unknown transparent; `step` cells per pixel (occupied wins)."""
    h, w = (g.shape[0] // step) * step, (g.shape[1] // step) * step
    b = g[:h, :w].reshape(h // step, step, w // step, step)
    occ = (b >= 65).any(axis=(1, 3))
    free = ((b >= 0) & (b < 25)).any(axis=(1, 3)) & ~occ
    img = np.zeros(occ.shape + (4,), np.uint8)
    img[free] = (255, 255, 255, 235)
    img[occ] = (11, 11, 11, 255)
    return base64.b64encode(png_rgba(img)).decode(), h * 1.0, w * 1.0


def main():
    gpath, rpath, out = sys.argv[1:4]
    z = np.load(gpath)
    g, res, ox, oy = z["grid"], float(z["res"]), float(z["ox"]), float(z["oy"])
    meta = json.load(open(os.path.join(ROOT, "worlds", "forest_meta.json")))
    route = json.load(open(rpath))["points"]
    sx, sy, syaw = meta["spawn"]
    c, s = math.cos(syaw), math.sin(syaw)

    # how well the map sits on the world: true trunk centre -> nearest occupied cell (map frame)
    occ_i, occ_j = np.nonzero(g >= 65)
    occ_xy = np.stack([ox + (occ_j + 0.5) * res, oy + (occ_i + 0.5) * res], 1)
    dists = []
    for tx, ty, *_ in meta["crowns"]:
        dx, dy = tx - sx, ty - sy
        mx, my = c * dx + s * dy, -s * dx + c * dy             # world -> map frame
        near = occ_xy[(np.abs(occ_xy[:, 0] - mx) < 1.5) & (np.abs(occ_xy[:, 1] - my) < 1.5)]
        if len(near):
            dists.append(float(np.min(np.hypot(near[:, 0] - mx, near[:, 1] - my))))
    dists.sort()
    med = dists[len(dists) // 2]
    p95 = dists[int(0.95 * (len(dists) - 1))]

    W, pad, head = 1200, 8.0, 56
    xs = [p[0] for p in meta["fence_posts"]] + [p[0] for p in route]
    ys = [p[1] for p in meta["fence_posts"]] + [p[1] for p in route]
    bx0, bx1, by0, by1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    k = W / (bx1 - bx0)
    map_h = (by1 - by0) * k
    zw_m, zh_m, zk = 26.0, 17.0, 22.0
    zw, zh = zw_m * zk, zh_m * zk
    gap = (W - 2 * zw) / 3
    zy = head + map_h + 46
    H = int(zy + zh + 78)
    over_b64, gh, gw = grid_png(g, 2)
    full_b64, fgh, fgw = grid_png(g, 1)

    def frame(kk, x0, y_top, wx0, wy1):
        """SVG matrix: map-frame metres -> px for a view whose world top-left (wx0, wy1) sits at (x0, y_top)."""
        return "matrix(%.6f %.6f %.6f %.6f %.3f %.3f)" % (kk * c, -kk * s, -kk * s, -kk * c,
                                                          x0 + kk * (sx - wx0), y_top + kk * (wy1 - sy))

    def layer(b64, gh_, gw_, step, kk, x0, y_top, wx0, wy1):
        return ('<g transform="%s"><image x="%.3f" y="%.3f" width="%.3f" height="%.3f" preserveAspectRatio="none" '
                'style="image-rendering:pixelated" href="data:image/png;base64,%s"/></g>'
                % (frame(kk, x0, y_top, wx0, wy1), ox, oy, gw_ * res, gh_ * res, b64))

    def world(kk, x0, y_top, wx0, wy1):
        return lambda x, y: (x0 + (x - wx0) * kk, y_top + (wy1 - y) * kk)

    def seen(tx, ty, r=1.0):
        """Has the map seen anything within r m of this world point? (Not the point itself: a trunk's inside stays
        unknown.)"""
        dx, dy = tx - sx, ty - sy
        j = int((c * dx + s * dy - ox) / res); i = int((-s * dx + c * dy - oy) / res)
        n = int(r / res)
        win = g[max(0, i - n):i + n + 1, max(0, j - n):j + n + 1]
        return win.size > 0 and bool((win >= 0).any())

    def overlays(tf, kk, box=None, zoom=False):
        o = []
        x0, y0, x1, y1 = box or (-1e9, -1e9, 1e9, 1e9)
        ins = lambda x, y: x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1
        pts = [p for p in route if ins(*p)] if box else route
        if len(pts) > 1:
            o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linejoin="round" '
                     'opacity="0.9"/>' % (" ".join("%.1f,%.1f" % tf(*p) for p in pts[::1 if zoom else 2]), ROUTE_C,
                                          3.0 if zoom else 2.0))
        for tx, ty, *_ in meta["crowns"]:
            if ins(tx, ty) and seen(tx, ty):
                px, py = tf(tx, ty)
                o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="%.1f"/>'
                         % (px, py, (0.55 if zoom else 0.9) * kk, TRUNK_C, 2.0 if zoom else 1.0))
        if zoom:
            for fx, fy in meta["fence_posts"]:
                if ins(fx, fy):
                    px, py = tf(fx, fy)
                    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="2"/>'
                             % (px, py, 0.35 * kk, POST_C))
        return o

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H),
           "<title>The ground robot's SLAM map against the true forest</title>",
           '<rect width="%d" height="%d" rx="10" fill="%s"/>' % (W, H, PAPER)]
    x = 16
    for kind, color, label in (("sq", INK, "occupied in the SLAM map"), ("sq", "#ffffff", "seen free"),
                               ("ring", TRUNK_C, "true trunk position"), ("line", ROUTE_C, "taught route, as the map sees it")):
        if kind == "sq":
            svg.append('<rect x="%d" y="20" width="16" height="16" rx="3" fill="%s" stroke="%s" stroke-width="1"/>'
                       % (x, color, INK2))
        elif kind == "ring":
            svg.append('<circle cx="%d" cy="28" r="7" fill="none" stroke="%s" stroke-width="2"/>' % (x + 8, color))
        else:
            svg.append('<line x1="%d" y1="28" x2="%d" y2="28" stroke="%s" stroke-width="3"/>' % (x, x + 22, color))
        svg.append('<text x="%d" y="33" %s font-size="14" fill="%s">%s</text>' % (x + 30, FONT, INK, label))
        x += 30 + int(7.4 * len(label)) + 28
    svg.append('<clipPath id="m"><rect x="0" y="%d" width="%d" height="%.0f"/></clipPath><g clip-path="url(#m)">'
               % (head, W, map_h))
    svg.append(layer(over_b64, gh, gw, 2, k, 0, head, bx0, by1))
    tf = world(k, 0, head, bx0, by1)
    svg += overlays(tf, k)
    svg.append("</g>")

    # close-ups: the start (loop closure) and the point of the route farthest from it
    far = max(route, key=lambda p: math.hypot(p[0] - sx, p[1] - sy))
    zooms = [("1", "The start, where the teach run closed its loop", (sx + 4.0, sy + 2.0)),
             ("2", "The far side of the loop, %.0f m from the start" % math.hypot(far[0] - sx, far[1] - sy), tuple(far))]
    for tag, _t, (cx, cy) in zooms:
        ax, ay = tf(cx - zw_m / 2, cy + zh_m / 2)
        svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="%s" stroke-width="1.5"/>'
                   % (ax, ay, zw_m * k, zh_m * k, INK))
        svg.append('<text x="%.1f" y="%.1f" %s font-size="14" font-weight="700" fill="%s">%s</text>'
                   % (ax + 4, ay - 5, FONT, INK, tag))
    sb_y = head + map_h - 16
    svg.append('<rect x="12" y="%.0f" width="%.0f" height="24" rx="4" fill="%s" opacity="0.9"/>' % (sb_y - 14, 20 * k + 60, PAPER))
    svg.append('<line x1="20" y1="%.0f" x2="%.1f" y2="%.0f" stroke="%s" stroke-width="2"/>' % (sb_y, 20 + 20 * k, sb_y, INK))
    svg.append('<text x="%.1f" y="%.0f" %s font-size="13" fill="%s">20 m</text>' % (28 + 20 * k, sb_y + 4, FONT, INK))
    for n, (tag, title, (cx, cy)) in enumerate(zooms):
        x0 = gap + n * (zw + gap)
        wx0, wy1 = cx - zw_m / 2, cy + zh_m / 2
        svg.append('<text x="%.1f" y="%.1f" %s font-size="14" font-weight="600" fill="%s">%s  %s</text>'
                   % (x0, zy - 10, FONT, INK, tag, title))
        svg.append('<clipPath id="z%d"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6"/></clipPath>'
                   % (n, x0, zy, zw, zh))
        svg.append('<g clip-path="url(#z%d)"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                   % (n, x0, zy, zw, zh, PAPER))
        svg.append(layer(full_b64, fgh, fgw, 1, zk, x0, zy, wx0, wy1))
        svg += overlays(world(zk, x0, zy, wx0, wy1), zk, (wx0, wy1 - zh_m, wx0 + zw_m, wy1), zoom=True)
        svg.append("</g>")
        svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="none" stroke="%s" stroke-width="1.5"/>'
                   % (x0, zy, zw, zh, INK))
        svg.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
                   % (x0 + 12, zy + zh - 14, x0 + 12 + 5 * zk, zy + zh - 14, INK))
        svg.append('<text x="%.1f" y="%.1f" %s font-size="13" fill="%s" paint-order="stroke" stroke="#ffffff" '
                   'stroke-width="4">5 m</text>' % (x0 + 20 + 5 * zk, zy + zh - 10, FONT, INK))
    svg.append('<text x="%.1f" y="%d" %s font-size="13" fill="%s">Close-ups: fence posts are brown rings; black '
               'shapes without a ring are bushes, logs and rocks (only trees are listed in forest_meta.json).</text>'
               % (gap, H - 40, FONT, INK2))
    svg.append('<text x="%.1f" y="%d" %s font-size="13" fill="%s">From each true trunk centre to the nearest occupied '
               'cell: median %.2f m, p95 %.2f m over %d trunks (a trunk\'s radius is 0.14–0.32 m).</text>'
               % (gap, H - 20, FONT, INK2, med, p95, len(dists)))
    svg.append("</svg>")
    open(out, "w").write("\n".join(svg) + "\n")
    print("wrote %s: %d trunks in the map, centre to nearest occupied cell median %.2f m, p95 %.2f m"
          % (out, len(dists), med, p95))


if __name__ == "__main__":
    main()
