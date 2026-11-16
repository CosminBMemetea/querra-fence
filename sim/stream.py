"""Streams the simulated cameras as RTSP, like real cameras on the farm network.

Runs with the Gazebo Python (gz.transport13 + numpy) and the ffmpeg from the same environment.
Every Gazebo image topic becomes an H.264 stream on the relay (MediaMTX):

    /ground/rgb      -> rtsp://<relay>/ground/rgb       RGB on the mast
    /ground/thermal  -> rtsp://<relay>/ground/thermal   thermal on the mast (8-bit, warm = bright)
    /ground/depth    -> rtsp://<relay>/ground/depth     iToF on the gate post (0-8 m, near = bright)
    /fence_cam/image -> rtsp://<relay>/drone/cam        the drone's inspection camera

The Jetson opens these URLs exactly like real cameras; switching to the field only changes the URLs.
Set GARDIAN_RTSP to the relay base URL (default rtsp://127.0.0.1:8554).
"""
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

import numpy as np

from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image

RELAY = os.environ.get("GARDIAN_RTSP", "rtsp://127.0.0.1:8554").rstrip("/")
FFMPEG = os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin", "ffmpeg")
if not os.path.exists(FFMPEG):
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
DEPTH_MAX_M = 8.0
THERMAL_WINDOW_K = (268.15, 318.15)  # -5 .. 45 °C mapped to 0 .. 255 (warm = bright)
_thermal_logged = False

STREAMS = {
    "/ground/rgb": ("ground/rgb", 10),
    "/ground/thermal": ("ground/thermal", 9),
    "/ground/depth": ("ground/depth", 10),
    "/fence_cam/image": ("drone/cam", 15),
}
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def to_frame(msg):
    """Gazebo image -> (bytes, width, height, ffmpeg pix_fmt)."""
    w, h, step = msg.width, msg.height, msg.step
    if not w or not h:
        return None
    bpp = step // w if step else len(msg.data) // (w * h)
    raw = np.frombuffer(msg.data, dtype=np.uint8)
    if raw.size < h * step:
        return None
    rows = raw[: h * step].reshape(h, step)
    if bpp == 3:
        return rows[:, : w * 3].tobytes(), w, h, "rgb24"
    if bpp == 1:
        return rows[:, :w].tobytes(), w, h, "gray"
    if bpp == 2:  # 16-bit thermal: kelvin / 0.01
        global _thermal_logged
        k = rows[:, : w * 2].copy().view(np.uint16).reshape(h, w).astype(np.float32) * 0.01
        if not _thermal_logged:
            _thermal_logged = True
            print("[stream] thermal first frame: %.1f .. %.1f K (%.1f .. %.1f °C)" % (
                k.min(), k.max(), k.min() - 273.15, k.max() - 273.15), flush=True)
        lo, hi = THERMAL_WINDOW_K
        g = (255.0 * np.clip((k - lo) / (hi - lo), 0.0, 1.0)).astype(np.uint8)
        return g.tobytes(), w, h, "gray"
    if bpp == 4:  # depth in metres (float32); no return -> 0
        d = rows[:, : w * 4].copy().view(np.float32).reshape(h, w)
        d = np.nan_to_num(d, nan=DEPTH_MAX_M, posinf=DEPTH_MAX_M, neginf=DEPTH_MAX_M)
        g = (255.0 * (1.0 - np.clip(d / DEPTH_MAX_M, 0.0, 1.0))).astype(np.uint8)
        return g.tobytes(), w, h, "gray"
    return None


class Stream(threading.Thread):
    def __init__(self, path, fps):
        super().__init__(daemon=True)
        self.url = "%s/%s" % (RELAY, path)
        self.fps = fps
        self.q = queue.Queue(maxsize=2)
        self.proc = None
        self.shape = None
        self.sent = 0
        self.last_report = time.time()

    def push(self, frame):
        try:
            self.q.put_nowait(frame)
        except queue.Full:  # keep latency low: drop the oldest frame
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            self.q.put_nowait(frame)

    def start_ffmpeg(self, w, h, pix):
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", pix, "-s", "%dx%d" % (w, h), "-framerate", str(self.fps),
               "-use_wallclock_as_timestamps", "1", "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
               "-g", str(self.fps * 2), "-b:v", "1200k", "-f", "rtsp", "-rtsp_transport", "tcp", self.url]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        self.shape = (w, h, pix)
        print("[stream] %s (%dx%d %s)" % (self.url, w, h, pix), flush=True)

    def run(self):
        while running:
            try:
                data, w, h, pix = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.proc is None or self.proc.poll() is not None or self.shape != (w, h, pix):
                if self.proc is not None and self.proc.poll() is not None:
                    time.sleep(3)  # relay not reachable yet: retry calmly
                self.start_ffmpeg(w, h, pix)
            try:
                self.proc.stdin.write(data)
                self.sent += 1
            except (BrokenPipeError, OSError):
                self.proc = None
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()


def main():
    node = Node()
    streams = {}
    for topic, (path, fps) in STREAMS.items():
        st = Stream(path, fps)
        st.start()
        streams[topic] = st

        def cb(msg, st=st):
            fr = to_frame(msg)
            if fr:
                st.push(fr)
        node.subscribe(Image, topic, cb)
    print("[stream] publishing to %s with %s" % (RELAY, FFMPEG), flush=True)
    while running:
        time.sleep(0.5)
    print("[stream] stopped", flush=True)


if __name__ == "__main__":
    sys.exit(main())
