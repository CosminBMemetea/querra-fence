"""Wrap a LiDAR render (PREFIX.png, PREFIX.json from ugv_lidar_render.py) in an SVG with callouts and a legend.

  python tools/ugv_lidar_label.py PREFIX OUT.svg
"""
import base64, json, sys

pre, out = sys.argv[1], sys.argv[2]
info = json.load(open(pre + ".json"))
W, H = info["W"], info["H"]
img = base64.b64encode(open(pre + ".png", "rb").read()).decode()
FONT = 'font-family="system-ui, -apple-system, Segoe UI, sans-serif"'
INK, INK2, BG, FAULT = "#f0efec", "#c3c2b7", "#0d0d0d", "#d03b3b"
LEG = 64 + (30 if info.get("note") else 0)
s = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="%d" height="%d" '
     'viewBox="0 0 %d %d">' % (W, H + LEG, W, H + LEG),
     "<title>What the ground robot's LiDAR sees (%s)</title>" % info["view"],
     '<rect width="%d" height="%d" fill="%s"/>' % (W, H + LEG, BG),
     '<image x="0" y="0" width="%d" height="%d" xlink:href="data:image/png;base64,%s"/>' % (W, H, img)]


def text(x, y, anchor, size, weight, fill, t):
    s.append('<text x="%.0f" y="%.0f" text-anchor="%s" %s font-size="%d" font-weight="%s" fill="%s" paint-order="stroke" '
             'stroke="%s" stroke-width="5" stroke-linejoin="round">%s</text>' % (x, y, anchor, FONT, size, weight, fill, BG, t))


for c in info["callouts"]:
    (ax, ay), dx, dy = c["at"], c["dx"], c["dy"]
    if info["view"] == "loop" and c["text"].startswith("F"):   # faults on the whole-loop view: a red dot and its id
        s.append('<circle cx="%.0f" cy="%.0f" r="6" fill="%s" stroke="%s" stroke-width="2"/>' % (ax, ay, FAULT, BG))
        text(ax, ay - 12, "middle", 17, 700, INK, c["text"])
        continue
    tx, ty = ax + dx, ay + dy
    if dx or dy:
        s.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="%s" stroke-width="1.5"/>' % (ax, ay, tx, ty, INK))
        s.append('<circle cx="%.0f" cy="%.0f" r="3.5" fill="%s"/>' % (ax, ay, INK))
    anchor, ox = ("start", 8) if dx >= 0 else ("end", -8)
    text(tx + ox, ty + 6, anchor, 20, 600, INK, c["text"])
    if c.get("sub"):
        text(tx + ox, ty + 28, anchor, 16, 400, INK2, c["sub"])
y = H + 32
x = 24
route_label = "the robot's route" if info["view"] == "loop" or info["view"].startswith("F") else "path driven"
for kind, color, t in (("dot", "#f08a5a", "0.33–1.68 m above the ground: the slice SLAM matches against its map"),
                       ("dot", "#6da7ec", "every other return, lighter = higher"),
                       ("line", INK, route_label)):
    if info["view"] == "single" and kind == "line":
        continue
    if kind == "dot":
        s.append('<circle cx="%d" cy="%d" r="7" fill="%s"/>' % (x + 7, y, color))
    else:
        s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3"/>' % (x, y, x + 24, y, color))
    s.append('<text x="%d" y="%d" %s font-size="17" fill="%s">%s</text>' % (x + 34, y + 6, FONT, INK, t))
    x += 34 + int(8.6 * len(t)) + 40
if info.get("note"):
    s.append('<text x="24" y="%d" %s font-size="15" fill="%s">%s</text>' % (y + 34, FONT, INK2, info["note"]))
s.append("</svg>")
open(out, "w").write("\n".join(s))
