"""Renders still images of the pasture world from fixed viewpoints (for comparing looks and for docs/media).

    tools/snap_world.sh [--look rich|classic] [--out run/snaps] [--width 1280 --height 720]

Generates the world with gen_world.py in the chosen look (no drone, no PX4), adds a free camera, starts a headless
Gazebo server, moves the camera to each viewpoint and saves a PNG. Also prints the mean colour of the ground in the
"inspection" view (the drone's camera pose), so the rich look can be kept close to the detector's training look.
Run it from a normal Terminal (Gazebo's renderer does not start in some sandboxed shells).
"""
import argparse
import math
import os
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
import gen_world  # noqa: E402
from make_textures import write_png  # noqa: E402

from gz.transport13 import Node  # noqa: E402
from gz.msgs10.boolean_pb2 import Boolean  # noqa: E402
from gz.msgs10.image_pb2 import Image  # noqa: E402
from gz.msgs10.pose_pb2 import Pose  # noqa: E402


def quat(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = (math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2),
                              math.cos(yaw / 2), math.sin(yaw / 2))
    return (cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy)


def look_at(eye, target):
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    return (*eye, 0.0, math.atan2(-dz, math.hypot(dx, dy)), math.atan2(dy, dx))


def viewpoints(cfg, fence):
    cx = sum(p[0] for p in fence.poly) / len(fence.poly)
    cy = sum(p[1] for p in fence.poly) / len(fence.poly)
    p0 = fence.posts[0]
    f1 = next(ft for ft in cfg["faults"] if ft["type"] == "wire_break")
    ax, ay, _ = fence.fault_anchor(f1)
    ox, oy = fence.fault_out(f1)
    herd = geo.herd_layout(cfg, fence)
    inside = [a for a in herd if geo.inside(fence.poly, a["x"], a["y"])][:6]
    hx = sum(a["x"] for a in inside) / len(inside)
    hy = sum(a["y"] for a in inside) / len(inside)
    # inspection: the drone's camera, 12 m up, 2.5 m outside the wire, pitched 55 deg down, looking along the fence
    tx, ty = -oy, ox
    ins = (ax + ox * 2.5 - tx * 12, ay + oy * 2.5 - ty * 12, 12.0, 0.0, math.radians(55), math.atan2(ty, tx))
    return [
        ("overview", look_at((cx - 95, cy - 120, 58), (cx + 10, cy + 15, 0))),
        ("farmyard", look_at((-2, -44, 7), (-28, -12, 3))),
        ("fence", look_at((p0["x"] + 9, p0["y"] - 7, 1.4), (p0["x"] + 40, p0["y"] + 30, 1.0))),
        ("herd", look_at((hx - 22, hy - 18, 7), (hx, hy, 0.8))),
        ("inspection", ins),
    ]


CAM = ('<model name="snap_cam"><pose>0 0 30 0 0.5 0</pose><link name="link"><gravity>false</gravity>'
       '<inertial><mass>1</mass><inertia><ixx>1</ixx><ixy>0</ixy><ixz>0</ixz><iyy>1</iyy><iyz>0</iyz><izz>1</izz></inertia></inertial>'
       '<sensor name="cam" type="camera"><camera><horizontal_fov>{hfov}</horizontal_fov><image><width>{w}</width><height>{h}</height></image>'
       '<clip><near>0.1</near><far>2000</far></clip></camera><always_on>1</always_on><update_rate>10</update_rate>'
       '<topic>/snap_cam/image</topic></sensor></link></model>')


class Frames:
    def __init__(self, w, h):
        self.w, self.h, self.lock, self.count, self.img = w, h, threading.Lock(), 0, None

    def cb(self, msg):
        if msg.width != self.w or msg.height != self.h:
            return
        a = np.frombuffer(msg.data, dtype=np.uint8)[: self.h * msg.step].reshape(self.h, msg.step)[:, : self.w * 3]
        with self.lock:
            self.img, self.count = a.reshape(self.h, self.w, 3).copy(), self.count + 1

    def wait_new(self, n0, k, timeout=20):
        t = time.time()
        while time.time() - t < timeout:
            with self.lock:
                if self.count >= n0 + k:
                    return self.img
            time.sleep(0.02)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--look", default="rich", choices=("rich", "classic"))
    ap.add_argument("--out", default=os.path.join(ROOT, "run", "snaps"))
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--hfov", type=float, default=1.2)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    gen_world.LOOK = a.look
    wpath = os.path.join(ROOT, "run", "snap_%s.sdf" % a.look)
    gen_world.OUT = wpath
    gen_world.main()
    s = open(wpath).read()
    s = re.sub(r"\s*<include>\s*<uri>model://x500_fence</uri>.*?</include>", "", s, flags=re.S)
    s = s.replace("  </world>", CAM.format(hfov=a.hfov, w=a.width, h=a.height) + "\n  </world>")
    open(wpath, "w").write(s)
    log = open(os.path.join(a.out, "gz_%s.log" % a.look), "w")
    t0 = time.time()
    gz = subprocess.Popen(["gz", "sim", "-r", "-s", "--verbose=2", wpath], stdout=log, stderr=subprocess.STDOUT)
    node, fr = Node(), Frames(a.width, a.height)
    node.subscribe(Image, "/snap_cam/image", fr.cb)
    try:
        while fr.count < 3 and time.time() - t0 < 120:
            time.sleep(0.3)
        if fr.count < 3:
            raise SystemExit("no camera frames (see %s)" % log.name)
        print("[snap] %s look: first frame after %.0f s" % (a.look, time.time() - t0), flush=True)
        for name, (x, y, z, r, p, yw) in viewpoints(cfg, fence):
            req = Pose()
            req.name = "snap_cam"
            req.position.x, req.position.y, req.position.z = x, y, z
            q = quat(r, p, yw)
            req.orientation.w, req.orientation.x, req.orientation.y, req.orientation.z = q
            with fr.lock:
                n0 = fr.count
            ok, _ = node.request("/world/pasture/set_pose", req, Pose, Boolean, 2000)
            img = fr.wait_new(n0, 4) if ok else None
            if img is None:
                print("[snap] %s: no frame" % name, flush=True)
                continue
            path = os.path.join(a.out, "%s_%s.png" % (a.look, name))
            write_png(path, img)
            extra = ""
            if name == "inspection":
                lower = img[int(a.height * 0.55):, :, :].reshape(-1, 3).mean(0)
                extra = " · mean colour of the lower image (mostly ground) %s" % np.round(lower).astype(int).tolist()
            print("[snap] %s%s" % (path, extra), flush=True)
    finally:
        gz.terminate()
        try:
            gz.wait(10)
        except subprocess.TimeoutExpired:
            gz.kill()
        subprocess.run(["pkill", "-f", wpath])
        log.close()


if __name__ == "__main__":
    main()
