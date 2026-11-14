"""Generează worlds/pasture.sdf din fence.json (gard, defecte, copaci, turmă, drona X500)."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402

OUT = os.path.join(geo.ROOT, "worlds", "pasture.sdf")


def mat(r, g, b, emissive=None, spec=0.08):
    e = emissive or (0, 0, 0)
    return ("<material><ambient>{0:.3f} {1:.3f} {2:.3f} 1</ambient><diffuse>{0:.3f} {1:.3f} {2:.3f} 1</diffuse>"
            "<specular>{3} {3} {3} 1</specular><emissive>{4:.3f} {5:.3f} {6:.3f} 1</emissive></material>").format(
        r, g, b, spec, e[0], e[1], e[2])


class Visuals:
    def __init__(self):
        self.items = []
        self.n = 0

    def add(self, geom, pose, material, shadows=True):
        self.n += 1
        self.items.append(
            '<visual name="v{n}"><pose>{p}</pose><geometry>{g}</geometry>{m}<cast_shadows>{s}</cast_shadows></visual>'.format(
                n=self.n, p=" ".join("%.4f" % v for v in pose), g=geom, m=material, s="true" if shadows else "false"))

    def box(self, size, pose, material, shadows=True):
        self.add("<box><size>%.3f %.3f %.3f</size></box>" % size, pose, material, shadows)

    def cyl(self, r, length, pose, material, shadows=True):
        self.add("<cylinder><radius>%.4f</radius><length>%.4f</length></cylinder>" % (r, length), pose, material, shadows)

    def sphere(self, r, pose, material, shadows=True):
        self.add("<sphere><radius>%.3f</radius></sphere>" % r, pose, material, shadows)

    def ellipsoid(self, radii, pose, material, shadows=True):
        self.add("<ellipsoid><radii>%.3f %.3f %.3f</radii></ellipsoid>" % radii, pose, material, shadows)

    def rod(self, a, b, r, material, shadows=False):
        """Cilindru între punctele 3D a și b."""
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        L = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-3
        pitch = math.atan2(math.hypot(dx, dy), dz)
        yaw = math.atan2(dy, dx)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
        self.cyl(r, L, (mid[0], mid[1], mid[2], 0, pitch, yaw), material, shadows)

    def xml(self):
        return "\n".join(self.items)


def static_model(name, visuals, pose=(0, 0, 0, 0, 0, 0)):
    return ('<model name="{n}"><static>true</static><pose>{p}</pose><link name="link">\n{v}\n</link></model>'.format(
        n=name, p=" ".join("%.4f" % v for v in pose), v=visuals.xml()))


def mover_model(name, visuals, pose):
    """Model fără coliziuni și fără gravitație: îl mută sim/director.py cu set_pose (animalele)."""
    return ('<model name="{n}"><pose>{p}</pose><link name="link"><gravity>false</gravity>'
            '<inertial><mass>300</mass><inertia><ixx>50</ixx><ixy>0</ixy><ixz>0</ixz><iyy>50</iyy><iyz>0</iyz><izz>50</izz></inertia></inertial>'
            '\n{v}\n</link></model>').format(n=name, p=" ".join("%.4f" % v for v in pose), v=visuals.xml())


WOOD = mat(0.42, 0.30, 0.19)
WOOD_DARK = mat(0.30, 0.21, 0.13)
WIRE = mat(0.95, 0.85, 0.35, emissive=(0.55, 0.42, 0.05), spec=0.4)
WIRE_DEAD = mat(0.35, 0.33, 0.30)
LEAF = [mat(0.20, 0.38, 0.12), mat(0.25, 0.44, 0.15), mat(0.17, 0.33, 0.13), mat(0.30, 0.45, 0.16)]
BARK = mat(0.33, 0.24, 0.17)


def build_fence(fence):
    v = Visuals()
    P = fence.posts
    for i, p in enumerate(P):
        h = 1.35 if p["corner"] else 1.2
        r = 0.075 if p["corner"] else 0.05
        a = p["tilt"]
        ox, oy = p["out"]
        top = (p["x"] + ox * math.sin(a) * h, p["y"] + oy * math.sin(a) * h, math.cos(a) * h)
        v.rod((p["x"], p["y"], 0.0), top, r, WOOD if not p["corner"] else WOOD_DARK, shadows=True)
    broken_seg = {seg: st for (seg, st) in fence.broken}
    for k in range(len(P) - 1):
        for st in range(len(fence.heights)):
            a = fence.attach(k, st)
            b = fence.attach(k + 1, st)
            if broken_seg.get(k) == st:
                # fir rupt: două capete atârnate până la sol
                for (p0, p1, frac) in ((a, b, 0.32), (b, a, 0.38)):
                    mid = (p0[0] + (p1[0] - p0[0]) * 0.12, p0[1] + (p1[1] - p0[1]) * 0.12, p0[2] * 0.35)
                    end = (p0[0] + (p1[0] - p0[0]) * frac, p0[1] + (p1[1] - p0[1]) * frac, 0.02)
                    v.rod(p0, mid, 0.018, WIRE_DEAD)
                    v.rod(mid, end, 0.018, WIRE_DEAD)
                continue
            dead = any(bs == st and k > seg for seg, bs in fence.broken)
            v.rod(a, b, 0.018, WIRE_DEAD if dead else WIRE)
    # poarta (mâner izolat) între ultimul stâlp și primul
    g, f0 = P[-1], P[0]
    v.rod((g["x"], g["y"], 1.0), (f0["x"], f0["y"], 1.0), 0.012, WIRE)
    v.box((0.25, 0.06, 0.06), ((g["x"] + f0["x"]) / 2, (g["y"] + f0["y"]) / 2, 1.0, 0, 0, math.atan2(f0["y"] - g["y"], f0["x"] - g["x"])), mat(0.08, 0.08, 0.08))
    # energizatorul la primul stâlp + LED
    ox, oy = f0["out"]
    ex, ey = f0["x"] + ox * 0.35, f0["y"] + oy * 0.35
    v.box((0.32, 0.22, 0.38), (ex, ey, 1.05, 0, 0, 0), mat(0.18, 0.2, 0.22))
    v.sphere(0.04, (ex + ox * 0.12, ey + oy * 0.12, 1.2, 0, 0, 0), mat(1, 0.1, 0.05, emissive=(1, 0.1, 0.05)), shadows=False)
    # plăcuța galbenă de avertizare
    s1 = P[2]
    v.box((0.3, 0.01, 0.16), (s1["x"] + s1["out"][0] * 0.06, s1["y"] + s1["out"][1] * 0.06, 0.8, 0, 0, math.atan2(s1["tan"][1], s1["tan"][0])), mat(0.98, 0.8, 0.05))
    return v


def add_tree(v, x, y, rnd, scale=1.0):
    h = rnd.uniform(2.6, 3.6) * scale
    v.cyl(0.22 * scale, h, (x, y, h / 2, 0, 0, 0), BARK)
    r = rnd.uniform(2.0, 3.0) * scale
    v.sphere(r, (x, y, h + r * 0.7, 0, 0, 0), rnd.choice(LEAF))
    v.sphere(r * 0.7, (x + rnd.uniform(-1, 1), y + rnd.uniform(-1, 1), h + r * 1.35, 0, 0, 0), rnd.choice(LEAF))


def build_scenery(cfg, fence):
    rnd = random.Random(cfg.get("seed", 1) + 11)
    v = Visuals()
    poly = fence.poly
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    trees = 0
    tries = 0
    while trees < 46 and tries < 6000:
        tries += 1
        a = rnd.uniform(0, 2 * math.pi)
        d = rnd.uniform(95, 190)
        x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
        if geo.inside(poly, x, y) or geo.dist_to_polyline(poly, x, y)[0] < 16:
            continue
        if math.hypot(x, y) < 26 or (x < 0 and abs(y + 16) < 8):
            continue
        add_tree(v, x, y, rnd, rnd.uniform(0.85, 1.25))
        trees += 1
    # pâlc de umbră în interior
    for (x, y) in ((cx + 8, cy + 10), (cx + 13, cy + 5), (cx + 4, cy + 15)):
        add_tree(v, x, y, rnd, 1.1)
    # copacul de lângă defectul "creangă pe gard" + creanga căzută peste fire
    for ft in cfg["faults"]:
        if ft["type"] == "branch_short":
            ax, ay, _ = fence.fault_anchor(ft)
            ox, oy = fence.fault_out(ft)
            tx, ty = ax + ox * 4.0, ay + oy * 4.0
            add_tree(v, tx, ty, rnd, 1.15)
            start = (tx - ox * 0.3, ty - oy * 0.3, 3.2)
            end = (ax - ox * 2.2, ay - oy * 2.2, 0.05)
            v.rod(start, end, 0.13, BARK, shadows=True)
            for f in (0.45, 0.7, 0.92):
                p = (start[0] + (end[0] - start[0]) * f, start[1] + (end[1] - start[1]) * f, start[2] + (end[2] - start[2]) * f + 0.4)
                v.sphere(0.75, (p[0], p[1], p[2], 0, 0, 0), rnd.choice(LEAF))
    # grajd, drum, adăpătoare, platforma dronei
    v.box((10, 7, 4.2), (-24, -16, 2.1, 0, 0, 0.1), mat(0.55, 0.22, 0.15))
    v.box((10.6, 4.3, 0.18), (-24 - 0.2, -16 - 1.85, 4.85, 0.62, 0, 0.1), mat(0.22, 0.22, 0.24))
    v.box((10.6, 4.3, 0.18), (-24 + 0.2, -16 + 1.85, 4.85, -0.62, 0, 0.1), mat(0.22, 0.22, 0.24))
    v.box((0.1, 2.6, 3.0), (-18.95, -15.4, 1.5, 0, 0, 0.1), mat(0.35, 0.2, 0.12))
    v.box((140, 3.6, 0.02), (-90, -18, 0.012, 0, 0, 0.02), mat(0.55, 0.46, 0.33), shadows=False)
    v.box((2.6, 0.8, 0.55), (cx - 6, cy - 4, 0.27, 0, 0, 0.4), mat(0.45, 0.5, 0.55))
    v.box((2.4, 0.6, 0.02), (cx - 6, cy - 4, 0.555, 0, 0, 0.4), mat(0.25, 0.42, 0.55, emissive=(0.02, 0.05, 0.08)), shadows=False)
    v.cyl(1.6, 0.02, (0, 0, 0.01, 0, 0, 0), mat(0.25, 0.26, 0.27), shadows=False)
    v.cyl(1.35, 0.022, (0, 0, 0.012, 0, 0, 0), mat(0.95, 0.55, 0.1), shadows=False)
    v.cyl(1.15, 0.024, (0, 0, 0.014, 0, 0, 0), mat(0.25, 0.26, 0.27), shadows=False)
    for (sx, sy, px, py) in ((0.12, 1.0, -0.3, 0), (0.12, 1.0, 0.3, 0), (0.6, 0.12, 0, 0)):
        v.box((sx, sy, 0.01), (px, py, 0.027, 0, 0, 0), mat(0.95, 0.95, 0.95), shadows=False)
    return v


COW_COLORS = {
    "holstein": ((0.93, 0.92, 0.89), (0.08, 0.08, 0.08), (0.93, 0.92, 0.89)),
    "baltata": ((0.56, 0.27, 0.12), (0.90, 0.87, 0.82), (0.90, 0.87, 0.82)),
    "bruna": ((0.46, 0.37, 0.29), (0.34, 0.27, 0.21), (0.40, 0.32, 0.25)),
}


def build_animal(a):
    v = Visuals()
    if a["kind"] == "cow":
        body, patch, head = COW_COLORS[a["breed"]]
        B, Pm, H = mat(*body), mat(*patch), mat(*head)
        v.box((1.9, 0.74, 0.82), (0, 0, 1.05, 0, 0, 0), B)
        v.box((0.62, 0.76, 0.5), (-0.35, 0, 1.12, 0, 0, 0), Pm)
        v.box((0.4, 0.76, 0.34), (0.5, 0, 0.98, 0, 0, 0), Pm)
        v.box((0.55, 0.42, 0.46), (1.12, 0, 1.3, 0, 0.25, 0), H)
        v.box((0.22, 0.34, 0.26), (1.42, 0, 1.17, 0, 0.25, 0), mat(0.75, 0.55, 0.5))
        v.box((0.08, 0.6, 0.06), (1.02, 0, 1.55, 0, 0, 0), mat(0.85, 0.82, 0.7), shadows=False)
        for (lx, ly) in ((0.72, 0.26), (0.72, -0.26), (-0.72, 0.26), (-0.72, -0.26)):
            v.cyl(0.08, 0.68, (lx, ly, 0.34, 0, 0, 0), mat(*[c * 0.85 for c in body]))
        v.box((0.05, 0.05, 0.62), (-0.98, 0, 0.88, 0, -0.15, 0), Pm, shadows=False)
    else:
        W, D = mat(0.93, 0.91, 0.84), mat(0.17, 0.15, 0.14)
        v.ellipsoid((0.58, 0.34, 0.36), (0, 0, 0.74, 0, 0, 0), W)
        v.box((0.32, 0.22, 0.26), (0.62, 0, 0.88, 0, 0.35, 0), D)
        v.box((0.1, 0.36, 0.05), (0.56, 0, 0.98, 0, 0, 0), D, shadows=False)
        for (lx, ly) in ((0.3, 0.15), (0.3, -0.15), (-0.3, 0.15), (-0.3, -0.15)):
            v.cyl(0.04, 0.48, (lx, ly, 0.24, 0, 0, 0), D)
    return mover_model(a["id"], v, (a["x"], a["y"], 0, 0, 0, a["yaw"]))


def main():
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    o = cfg["origin"]
    parts = [
        static_model("gard_electric", build_fence(fence)),
        static_model("peisaj", build_scenery(cfg, fence)),
    ]
    for a in geo.herd_layout(cfg, fence):
        parts.append(build_animal(a))
    # puncte invizibile pe care camera GUI le poate urmări (centrul pășunii, energizatorul, fiecare defect)
    cx = sum(p[0] for p in fence.poly) / len(fence.poly)
    cy = sum(p[1] for p in fence.poly) / len(fence.poly)
    p0 = fence.posts[0]
    focus = [("focus_center", cx, cy, 0.0), ("focus_energizer", p0["x"] + 3, p0["y"] + 2, 0.8)]
    focus += [("focus_" + ft["id"], fence.fault_anchor(ft)[0], fence.fault_anchor(ft)[1], 0.6) for ft in cfg["faults"]]
    for name, x, y, z in focus:
        parts.append('<model name="%s"><static>true</static><pose>%.3f %.3f %.3f 0 0 0</pose><link name="link"/></model>' % (name, x, y, z))

    world = """<?xml version="1.0" encoding="UTF-8"?>
<!-- GENERAT de sim/gen_world.py din fence.json. Nu edita de mână: schimbă fence.json. -->
<sdf version="1.9">
  <world name="pasture">
    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene>
      <grid>false</grid>
      <ambient>0.55 0.55 0.55 1</ambient>
      <background>0.62 0.77 0.93 1</background>
      <shadows>true</shadows>
    </scene>
    <spherical_coordinates>
      <surface_model>EARTH_WGS84</surface_model>
      <world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>{lat}</latitude_deg>
      <longitude_deg>{lon}</longitude_deg>
      <elevation>{alt}</elevation>
    </spherical_coordinates>
    <light name="soare" type="directional">
      <pose>0 0 300 0 0 0</pose>
      <cast_shadows>true</cast_shadows>
      <intensity>1.1</intensity>
      <direction>-0.45 0.4 -0.8</direction>
      <diffuse>1.0 0.95 0.86 1</diffuse>
      <specular>0.3 0.3 0.3 1</specular>
    </light>
    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>1 1</size></plane></geometry></collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>900 900</size></plane></geometry>
          <material><ambient>0.30 0.45 0.18 1</ambient><diffuse>0.30 0.45 0.18 1</diffuse><specular>0.02 0.02 0.02 1</specular></material>
        </visual>
      </link>
    </model>
    <include>
      <uri>model://x500_fence</uri>
      <name>x500_fence</name>
      <pose>0 0 0.05 0 0 0</pose>
    </include>
{parts}
  </world>
</sdf>
""".format(lat=o["lat"], lon=o["lon"], alt=o["alt_m"], parts="\n".join(parts))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(world)
    print("[gen_world] %s: %d stâlpi, gard %.0f m, %d defecte, %d animale" % (
        os.path.relpath(OUT, geo.ROOT), len(fence.posts), fence.length, len(cfg["faults"]),
        cfg["herd"]["cows"] + cfg["herd"]["sheep"]))


if __name__ == "__main__":
    main()
