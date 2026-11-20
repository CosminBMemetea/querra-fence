"""Simulator camera node: publishes the Gazebo inspection camera and the drone telemetry.

Two sources, same topics (camera/image_raw/compressed + telemetry, in the node's namespace, e.g. /sim):
- source:=tcp://HOST:PORT  live QFC1 stream from tools/cam_stream.py on the Mac (simulation running)
- source:=DIR              a recording from tools/cam_record.py (frames.jsonl + frames/*.jpg), replayed at
                           real time and looped, so the demo works with no simulator and no network
"""
import json, math, os, socket, struct, threading, time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, NavSatFix, NavSatStatus
from querra_fence_msgs.msg import Telemetry

NAN = float("nan")


class SimCamera(Node):
    def __init__(self):
        super().__init__("sim_camera")
        self.source = self.declare_parameter("source", "/sim/m1").value
        self.rate = float(self.declare_parameter("rate", 1.0).value)        # replay speed
        self.max_fps = float(self.declare_parameter("max_fps", 15.0).value)
        self.frame_id = self.declare_parameter("frame_id", "sim_camera_optical").value
        self.pub_img = self.create_publisher(CompressedImage, "camera/image_raw/compressed", qos_profile_sensor_data)
        self.pub_tel = self.create_publisher(Telemetry, "telemetry", 10)
        self.pub_fix = self.create_publisher(NavSatFix, "gps/fix", 10)
        self._last = 0.0
        threading.Thread(target=self._tcp if self.source.startswith("tcp://") else self._replay, daemon=True).start()

    def _publish(self, jpeg, tel):
        now = time.monotonic()
        if now - self._last < 0.8 / self.max_fps:
            return
        self._last = now
        stamp = self.get_clock().now().to_msg()
        m = CompressedImage(format="jpeg", data=jpeg); m.header.stamp = stamp; m.header.frame_id = self.frame_id
        self.pub_img.publish(m)
        tel = tel or {}
        t = Telemetry(); t.header.stamp = stamp; t.header.frame_id = "base_link"
        g = lambda k: NAN if tel.get(k) is None else float(tel[k])
        t.latitude, t.longitude, t.altitude_m, t.heading_deg, t.speed_mps = g("lat"), g("lon"), g("alt_m"), g("heading_deg"), g("speed_ms")
        t.phase, t.source = str(tel.get("phase") or ""), "sim"
        self.pub_tel.publish(t)
        f = NavSatFix(); f.header.stamp = stamp; f.header.frame_id = "gps"
        f.latitude, f.longitude, f.altitude = t.latitude, t.longitude, float(t.altitude_m)
        f.status.status = NavSatStatus.STATUS_FIX if not math.isnan(t.latitude) else NavSatStatus.STATUS_NO_FIX
        f.status.service = NavSatStatus.SERVICE_GPS
        self.pub_fix.publish(f)

    def _load(self):
        """frames.jsonl rows (blank or broken lines skipped); [] with an error log if the recording is unusable."""
        path = os.path.join(self.source, "frames.jsonl")
        try:
            with open(path) as f:
                rows = []
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and "file" in r and "sim_time_s" in r:
                        rows.append(r)
        except OSError as e:
            self.get_logger().error(f"no recording at {path}: {e} (copy one to /ssd/querra/sim on the Jetson); retrying in 10 s")
            return []
        if not rows:
            self.get_logger().error(f"{path} has no usable frames; retrying in 10 s")
        return rows

    def _replay(self):
        rows = self._load()
        while not rows and rclpy.ok():
            time.sleep(10)
            rows = self._load()
        self.get_logger().info(f"replaying {len(rows)} frames from {self.source} at x{self.rate}, looped")
        while rclpy.ok():
            t0, s0 = time.monotonic(), rows[0]["sim_time_s"]
            for r in rows:
                wait = (r["sim_time_s"] - s0) / self.rate - (time.monotonic() - t0)
                if wait > 0:
                    time.sleep(wait)
                try:
                    jpeg = open(os.path.join(self.source, r["file"]), "rb").read()
                except OSError:
                    continue
                self._publish(jpeg, r.get("telemetry"))
            time.sleep(1.0)

    @staticmethod
    def _read(f, n):
        b = f.read(n)
        if len(b) != n:
            raise OSError(f"stream closed ({len(b)} of {n} bytes)")
        return b

    def _tcp(self):
        hostport = self.source[6:].strip("/")
        host, _, port = hostport.rpartition(":") if ":" in hostport else (hostport, "", "5601")
        try:
            port = int(port)
        except ValueError:
            self.get_logger().error(f"bad source {self.source}: expected tcp://HOST:PORT")
            return
        while rclpy.ok():
            try:
                with socket.create_connection((host, port), timeout=10) as s:
                    self.get_logger().info(f"connected to {host}:{port}")
                    f = s.makefile("rb")
                    while rclpy.ok():
                        if self._read(f, 4) != b"QFC1":
                            raise OSError("bad frame magic")
                        hl, jl = struct.unpack(">II", self._read(f, 8))
                        hdr = json.loads(self._read(f, hl)); jpeg = self._read(f, jl)
                        self._publish(jpeg, hdr.get("telemetry") if isinstance(hdr, dict) else None)
            except (OSError, ValueError, struct.error) as e:
                self.get_logger().warn(f"{host}:{port}: {e}; retrying in 3 s", throttle_duration_sec=30)
            time.sleep(3)


def main():
    rclpy.init(); n = SimCamera()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
