"""Sends the drone's inspection camera to the Jetson over the LAN, like a real onboard camera.

Subscribes to the Gazebo topic /fence_cam/image (640x400, 15 fps), encodes each frame as JPEG with
the ffmpeg of PX4's Gazebo environment, and serves it on a TCP port. Every frame carries a small JSON
header with the sim time, send time and the drone telemetry from run/drone_state.json (written by
sim/mission.py during a flight), so the Jetson gets "camera + GPS" in one stream.

Wire format, per frame:   b"QFC1" | uint32 BE header_len | uint32 BE jpeg_len | header JSON | JPEG
The Jetson connects as a client (querra-scout: --source sim:<mac-ip>:5601). Several clients may connect;
each one always gets the newest frame (old frames are dropped, never queued).

Run with tools/cam_stream.sh (sets up the Gazebo environment), on a simulation that is already running.
"""
import argparse
import json
import os
import queue
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "run", "drone_state.json")
MAGIC = b"QFC1"
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


class Telemetry:
    """Latest drone state from run/drone_state.json, re-read only when the file changes."""
    def __init__(self, path):
        self.path, self.mtime, self.state = path, None, None

    def get(self):
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            return None
        if m != self.mtime:
            try:
                with open(self.path) as f:
                    self.state = json.load(f)
                self.mtime = m
            except (OSError, ValueError):
                pass
        if not self.state:
            return None
        s = dict(self.state)
        s["age_s"] = round(time.time() - float(s.get("t", 0)), 3) if s.get("t") else None
        return s


class Encoder:
    """One long-lived ffmpeg: raw RGB frames in, one JPEG per frame out, in order."""
    def __init__(self, ffmpeg, quality, on_jpeg):
        self.ffmpeg, self.quality, self.on_jpeg = ffmpeg, quality, on_jpeg
        self.proc, self.shape = None, None
        self.pending = deque()

    def _start(self, w, h):
        if self.proc:
            self.close()
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "%dx%d" % (w, h), "-i", "-", "-an", "-c:v", "mjpeg", "-threads", "1", "-q:v", str(self.quality),
               "-pix_fmt", "yuvj420p", "-flush_packets", "1", "-f", "image2pipe", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.shape = (w, h)
        self.pending.clear()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        buf = b""
        while running:
            chunk = proc.stdout.read(65536)
            if not chunk:
                return
            buf += chunk
            while True:  # ffmpeg MJPEG: FF D9 only appears as the end-of-image marker
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    break
                jpeg, buf = buf[start:end + 2], buf[end + 2:]
                header = self.pending.popleft() if self.pending else {}
                header["encode_ms"] = round((time.time() - header.get("t_gz_recv", time.time())) * 1000, 1)
                self.on_jpeg(header, jpeg)

    def push(self, header, rgb, w, h):
        if self.proc is None or self.proc.poll() is not None or self.shape != (w, h):
            self._start(w, h)
        self.pending.append(header)
        try:
            self.proc.stdin.write(rgb)
        except (BrokenPipeError, OSError):
            self.proc = None

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()
            self.proc = None


class Server:
    def __init__(self, bind, port):
        self.clients = []
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind, port))
        self.sock.listen(4)
        self.sock.settimeout(0.5)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while running:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            q = queue.Queue(maxsize=1)
            with self.lock:
                self.clients.append(q)
            print("[cam_stream] client %s:%d connected" % addr, flush=True)
            threading.Thread(target=self._serve, args=(conn, addr, q), daemon=True).start()

    def _serve(self, conn, addr, q):
        sent = 0
        try:
            while running:
                try:
                    header, jpeg = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                header = dict(header, t_send=time.time())
                h = json.dumps(header, separators=(",", ":")).encode()
                conn.sendall(MAGIC + struct.pack(">II", len(h), len(jpeg)) + h + jpeg)
                sent += 1
        except OSError:
            pass
        finally:
            with self.lock:
                self.clients.remove(q)
            conn.close()
            print("[cam_stream] client %s:%d gone after %d frames" % (addr[0], addr[1], sent), flush=True)

    def publish(self, header, jpeg):
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait((header, jpeg))
            except queue.Full:  # client is slower than the camera: replace the stale frame
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                q.put_nowait((header, jpeg))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--topic", default="/fence_cam/image")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5601)
    ap.add_argument("--quality", type=int, default=4, help="ffmpeg -q:v, 2 (best) .. 31")
    args = ap.parse_args()

    ffmpeg = os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin", "ffmpeg")
    if not os.path.exists(ffmpeg):
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    server = Server(args.bind, args.port)
    stats = dict(frames=0, jpeg_bytes=0, t=time.time())

    def on_jpeg(header, jpeg):
        stats["frames"] += 1
        stats["jpeg_bytes"] += len(jpeg)
        server.publish(header, jpeg)

    encoder = Encoder(ffmpeg, args.quality, on_jpeg)
    telemetry = Telemetry(STATE)
    latest = queue.Queue(maxsize=1)
    seq = [0]

    def cb(msg):
        w, h, step = msg.width, msg.height, msg.step
        if not w or not h:
            return
        raw = np.frombuffer(msg.data, dtype=np.uint8)
        if step < w * 3 or raw.size < h * step:
            return
        rgb = raw[: h * step].reshape(h, step)[:, : w * 3].tobytes()
        stamp = msg.header.stamp.sec + msg.header.stamp.nsec * 1e-9
        seq[0] += 1
        header = dict(seq=seq[0], topic=args.topic, sim_time_s=round(stamp, 3), t_gz_recv=time.time(),
                      width=w, height=h, telemetry=telemetry.get())
        try:
            latest.put_nowait((header, rgb, w, h))
        except queue.Full:
            try:
                latest.get_nowait()
            except queue.Empty:
                pass
            latest.put_nowait((header, rgb, w, h))

    node = Node()
    if not node.subscribe(Image, args.topic, cb):
        print("[cam_stream] could not subscribe to %s" % args.topic, file=sys.stderr)
        return 1
    print("[cam_stream] %s -> tcp://%s:%d (JPEG q%d via %s)" % (args.topic, args.bind, args.port, args.quality, ffmpeg),
          flush=True)
    while running:
        try:
            header, rgb, w, h = latest.get(timeout=0.5)
            encoder.push(header, rgb, w, h)
        except queue.Empty:
            pass
        now = time.time()
        if now - stats["t"] >= 10:
            dt = now - stats["t"]
            print("[cam_stream] %.1f fps, %.0f KB/frame, %d client(s)" % (
                stats["frames"] / dt, stats["jpeg_bytes"] / max(1, stats["frames"]) / 1024, len(server.clients)),
                flush=True)
            stats.update(frames=0, jpeg_bytes=0, t=now)
    encoder.close()
    print("[cam_stream] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
