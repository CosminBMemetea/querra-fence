"""GPS node: one gpsd client (gpsd owns the u-blox port). Publishes gps/fix (sensor_msgs/NavSatFix, with fix status
and covariance from gpsd's error estimates) and gps/info (querra_fence_msgs/GpsInfo: fix type, satellites, HDOP, speed)."""
import json, math, socket, threading, time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, NavSatStatus
from querra_fence_msgs.msg import GpsInfo

NAN = float("nan")


def f(v):
    return NAN if v is None else float(v)


class GpsdGps(Node):
    def __init__(self):
        super().__init__("gpsd_gps")
        self.host = self.declare_parameter("host", "127.0.0.1").value
        self.port = self.declare_parameter("port", 2947).value
        self.frame_id = self.declare_parameter("frame_id", "gps").value
        self.pub_fix = self.create_publisher(NavSatFix, "gps/fix", 10)
        self.pub_info = self.create_publisher(GpsInfo, "gps/info", 10)
        self.sky, self.last_fix, self.device = {}, None, ""
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while rclpy.ok():
            try:
                with socket.create_connection((self.host, self.port), timeout=10) as s:
                    s.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    self.get_logger().info(f"connected to gpsd {self.host}:{self.port}")
                    for line in s.makefile("r", encoding="utf-8", errors="replace"):
                        try:
                            m = json.loads(line)
                        except ValueError:
                            continue
                        if m.get("class") == "SKY" and ("satellites" in m or "hdop" in m):
                            self.sky = m
                        elif m.get("class") == "TPV":
                            self._tpv(m)
            except OSError as e:
                self.get_logger().warn(f"gpsd: {e}; retrying in 3 s", throttle_duration_sec=30)
            time.sleep(3)

    def _tpv(self, t):
        stamp = self.get_clock().now().to_msg()
        mode = int(t.get("mode") or 0)
        self.device = t.get("device") or self.device
        if mode >= 2 and t.get("lat") is not None:
            self.last_fix = time.monotonic()
        fix = NavSatFix(); fix.header.stamp = stamp; fix.header.frame_id = self.frame_id
        fix.status.status = NavSatStatus.STATUS_FIX if mode >= 2 else NavSatStatus.STATUS_NO_FIX
        fix.status.service = NavSatStatus.SERVICE_GPS | NavSatStatus.SERVICE_GLONASS | NavSatStatus.SERVICE_GALILEO
        fix.latitude, fix.longitude = f(t.get("lat")), f(t.get("lon"))
        fix.altitude = f(t.get("altHAE", t.get("alt"))) if mode >= 3 else NAN
        ex, ey, ev = t.get("epx"), t.get("epy"), t.get("epv")
        if ex is not None and ey is not None:
            fix.position_covariance = [ex * ex, 0.0, 0.0, 0.0, ey * ey, 0.0, 0.0, 0.0, (ev or 100.0) ** 2]
            fix.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
        else:
            fix.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        self.pub_fix.publish(fix)
        k = self.sky; sats = k.get("satellites") or []
        info = GpsInfo(); info.header = fix.header
        info.mode = mode; info.fix = {2: "2D", 3: "3D"}.get(mode, "none")
        info.sats_used = int(k.get("uSat", sum(1 for x in sats if x.get("used"))))
        info.sats_seen = int(k.get("nSat", len(sats)))
        info.hdop, info.speed_mps, info.track_deg = f(k.get("hdop")), f(t.get("speed")), f(t.get("track"))
        info.fix_age_s = NAN if self.last_fix is None else float(time.monotonic() - self.last_fix)
        info.device = self.device or ""
        self.pub_info.publish(info)


def main():
    rclpy.init(); n = GpsdGps()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
