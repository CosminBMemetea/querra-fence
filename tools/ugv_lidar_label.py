"""Wrap a LiDAR render (PREFIX.png, PREFIX.json from ugv_lidar_render.py) in an SVG with callouts and a legend.

  python tools/ugv_lidar_label.py PREFIX OUT.svg VIEW
"""
import base64, json, sys

pre, out, view = sys.argv[1], sys.argv[2], sys.argv[3]
info = json.load(open(pre + ".json"))
W, H = info["W"], info["H"]
L = info["labels"]
img = base64.b64encode(open(pre + ".png", "rb").read()).decode()
FONT = 'font-family="system-ui, -apple-system, Segoe UI, sans-serif"'
INK, INK2, BG = "#f0efec", "#c3c2b7", "#0d0d0d"
LEG = 64
s = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="%d" height="%d" '
     'viewBox="0 0 %d %d">' % (W, H + LEG, W, H + LEG),
     '<title>What the ground robot\'s LiDAR sees: %.0f m of forest, %d scans</title>' % (info["metres"], info["scans"]),
     '<rect width="%d" height="%d" fill="%s"/>' % (W, H + LEG, BG),
     '<image x="0" y="0" width="%d" height="%d" xlink:href="data:image/png;base64,%s"/>' % (W, H, img)]


def callout(anchor, dx, dy, text, sub=None):
    ax, ay = anchor
    tx, ty = ax + dx, ay + dy
    s.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="%s" stroke-width="1.5"/>' % (ax, ay, tx, ty, INK))
    s.append('<circle cx="%.0f" cy="%.0f" r="3.5" fill="%s"/>' % (ax, ay, INK))
    anchor_txt = "start" if dx >= 0 else "end"
    ox = 8 if dx >= 0 else -8
    s.append('<text x="%.0f" y="%.0f" text-anchor="%s" %s font-size="20" font-weight="600" fill="%s" paint-order="stroke" '
             'stroke="%s" stroke-width="5" stroke-linejoin="round">%s</text>' % (tx + ox, ty + 6, anchor_txt, FONT, INK, BG, text))
    if sub:
        s.append('<text x="%.0f" y="%.0f" text-anchor="%s" %s font-size="16" fill="%s" paint-order="stroke" stroke="%s" '
                 'stroke-width="5" stroke-linejoin="round">%s</text>' % (tx + ox, ty + 28, anchor_txt, FONT, INK2, BG, sub))


if view == "back":
    callout(L["robot"], 90, -40, "the robot", "16-beam LiDAR, 0.52 m up")
    callout(L["post"], 70, 250, "fence: posts and wires")
    if "trunk" in L:
        callout(L["trunk"], 40, 170, "tree trunk")
    if "start" in L:
        callout(L["start"], -210, -40, "path driven", "%.0f m, %d scans" % (info["metres"], info["scans"]))
else:
    callout(L["robot"], 60, -70, "the robot")
    callout(L["post"], 120, -110, "fence: posts and wires")
    if "trunk" in L:
        callout(L["trunk"], 120, 60, "tree trunk")
y = H + LEG / 2
x = 24
for kind, color, text in (("dot", "#f08a5a", "0.33–1.68 m above the ground: the slice SLAM matches against its map"),
                          ("dot", "#6da7ec", "every other return, lighter = higher"),
                          ("line", INK, "path driven")):
    if kind == "dot":
        s.append('<circle cx="%d" cy="%d" r="7" fill="%s"/>' % (x + 7, y, color))
    else:
        s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3"/>' % (x, y, x + 24, y, color))
    s.append('<text x="%d" y="%d" %s font-size="17" fill="%s">%s</text>' % (x + 34, y + 6, FONT, INK, text))
    x += 34 + int(8.6 * len(text)) + 40
s.append("</svg>")
open(out, "w").write("\n".join(s))
