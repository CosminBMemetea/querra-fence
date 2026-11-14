"""Captures demo material while a mission runs (Gazebo Python env: gz.transport13 + numpy).

* GUI stills through the Screenshot plugin (/gui/screenshot) with scripted camera moves
* the drone's inspection camera (/fence_cam/image) around every detection, with the
  ground-truth poses of the drone and animals so tools/make_media.py can draw boxes

Started by `./start.sh demo`; writes into docs/media/raw/ (git-ignored).
"""
import collections
import json
import math
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim"))
import geo  # noqa: E402

from gz.transport13 import Node  # noqa: E402
from gz.msgs10.boolean_pb2 import Boolean  # noqa: E402
from gz.msgs10.cameratrack_pb2 import CameraTrack  # noqa: E402
from gz.msgs10.image_pb2 import Image  # noqa: E402
from gz.msgs10.pose_v_pb2 import Pose_V  # noqa: E402
from gz.msgs10.stringmsg_pb2 import StringMsg  # noqa: E402

RAW = os.path.join(geo.ROOT, "docs", "media", "raw")
GO_FILE = os.path.join(geo.RUN_DIR, "demo_go")
MISSION_LOG = os.path.join(geo.RUN_DIR, "mission.log")
EVENTS = os.path.join(geo.RUN_DIR, "events.jsonl")
DRONE = "x500_fence"
STREAM_HZ = 5.0
PRE_S, POST_S = 6.0, 8.0

node = Node()
lock = threading.Lock()
latest = {"img": None, "img_t": 0.0, "poses": {}}


def on_image(msg):
    h, w, step = msg.height, msg.width, msg.step
    arr = np.frombuffer(msg.data, dtype=np.uint8)
    if step and arr.size >= h * step:
        arr = arr[: h * step].reshape(h, step)[:, : w * 3].reshape(h, w, 3)
    else:
        return
    with lock:
        latest["img"] = arr.copy()
        latest["img_t"] = time.time()


def on_poses(msg):
    poses = {}
    for p in msg.pose:
        if p.name and p.name not in poses and p.name != "link":
            poses[p.name] = (p.position.x, p.position.y, p.position.z,
                             p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z)
    with lock:
        latest["poses"].update(poses)


track_pub = node.advertise("/gui/track", CameraTrack)


def track(offset, pgain=0.05, target=DRONE):
    """GUI camera follows `target` (a model) at `offset` and looks at it."""
    ct = CameraTrack()
    ct.track_mode = CameraTrack.FOLLOW_LOOK_AT
    ct.follow_target.name = target
    ct.track_target.name = target
    ct.follow_offset.x, ct.follow_offset.y, ct.follow_offset.z = offset
    ct.follow_pgain = pgain
    ct.track_pgain = min(1.0, pgain * 1.5)
    track_pub.publish(ct)


def frame(target, offset, settle=2.5):
    """Snap the camera to a still view around one of the invisible focus_* models."""
    track(offset, 1.0, target)
    time.sleep(settle)


def shot(name, wait=0.6):
    d = os.path.join(RAW, "gui", name)
    os.makedirs(d, exist_ok=True)
    req = StringMsg()
    req.data = d
    ok, _ = node.request("/gui/screenshot", req, StringMsg, Boolean, 3000)
    time.sleep(wait)
    return ok


def wait_gui(timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        if shot("_warmup"):
            return True
        time.sleep(1.0)
    return False


def mission_log():
    try:
        with open(MISSION_LOG, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


class Recorder(threading.Thread):
    """Inspection camera ring buffer; dumps windows around detections."""

    def __init__(self):
        super().__init__(daemon=True)
        self.buf = collections.deque(maxlen=int(PRE_S * STREAM_HZ))
        self.rec_until = 0.0
        self.n = 0
        self.dir = os.path.join(RAW, "stream")
        os.makedirs(self.dir, exist_ok=True)
        self.meta = open(os.path.join(self.dir, "frames.jsonl"), "w")
        self.running = True

    def trigger(self):
        if time.time() > self.rec_until:
            while self.buf:
                self._save(*self.buf.popleft())
        self.rec_until = time.time() + POST_S

    def _save(self, t, img, poses):
        self.n += 1
        np.save(os.path.join(self.dir, "%05d.npy" % self.n), img)
        self.meta.write(json.dumps({"i": self.n, "t": t, "poses": poses}) + "\n")
        self.meta.flush()

    def run(self):
        last_t = 0.0
        while self.running:
            time.sleep(1.0 / STREAM_HZ)
            with lock:
                img, t, poses = latest["img"], latest["img_t"], dict(latest["poses"])
            if img is None or t == last_t:
                continue
            last_t = t
            if time.time() < self.rec_until:
                self._save(t, img, poses)
            else:
                self.buf.append((t, img, poses))


def main():
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    poly = fence.poly
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    os.makedirs(RAW, exist_ok=True)
    node.subscribe(Image, "/fence_cam/image", on_image)
    node.subscribe(Pose_V, "/world/pasture/dynamic_pose/info", on_poses)
    print("[capture] waiting for the Gazebo GUI …", flush=True)
    if not wait_gui():
        print("[capture] GUI screenshot service not available", flush=True)
        open(GO_FILE, "w").close()
        return 1
    time.sleep(4)

    # 1. before takeoff: the whole pasture, then the drone on its pad
    frame("focus_center", (-45, -98, 58), 3.5)
    shot("01_pasture")
    frame(DRONE, (-2.6, -1.9, 0.95), 3.0)
    shot("02_drone_on_pad")
    frame("focus_energizer", (-12, -7, 2.2), 3.0)
    shot("03_fence_energizer")

    # 2. go: chase camera during takeoff and flight
    rec = Recorder()
    rec.start()
    track((-5.0, -3.5, 2.2), 0.08)
    open(GO_FILE, "w").close()
    print("[capture] mission go", flush=True)
    while "Armat" not in mission_log():
        time.sleep(0.5)
    t_arm = time.time()
    while time.time() - t_arm < 10:
        shot("04_takeoff", wait=0.2)
    track((-6.0, -4.0, 3.0), 0.08)

    seen_events = 0
    last_still = time.time()
    n_still = 0
    while "Aterizat" not in mission_log() and "Raport:" not in mission_log():
        try:
            with open(EVENTS, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        if len(lines) > seen_events:
            seen_events = len(lines)
            rec.trigger()
        if time.time() - last_still > 14 and n_still < 8:
            last_still = time.time()
            n_still += 1
            shot("05_flight")
        time.sleep(0.3)
    rec.running = False
    time.sleep(1.0)

    # 3. after landing: the result from above + close-ups of each fault
    frame("focus_center", (30, -104, 72), 4.0)
    shot("06_result_overview")
    for ft in cfg["faults"]:
        ox, oy = fence.fault_out(ft)
        tx, ty = -oy, ox
        frame("focus_" + ft["id"], (ox * 7 + tx * 5, oy * 7 + ty * 5, 3.6), 3.0)
        shot("07_fault_%s" % ft["id"])
    with open(os.path.join(RAW, "manifest.json"), "w") as f:
        json.dump({"frames": rec.n, "faults": [f["id"] for f in cfg["faults"]]}, f)
    print("[capture] done: %d camera frames" % rec.n, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
