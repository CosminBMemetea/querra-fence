"""LD2450 radar node: a client of the ld2450-radar service's SSE stream (http://127.0.0.1:8077/events).
The service owns /dev/ttyUSB0; this node never opens the serial port.

Publishes radar/targets (querra_fence_msgs/RadarTargets), radar/points (sensor_msgs/PointCloud2, REP 103 frame:
x forward, y left) and radar/markers (visualization_msgs/MarkerArray: target spheres, labels and the ±60° / 6 m field)."""
import json, math, threading, time, urllib.request
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from geometry_msgs.msg import Point
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from visualization_msgs.msg import Marker, MarkerArray
from querra_fence_msgs.msg import RadarTarget, RadarTargets

COLORS = [(0.18, 0.82, 0.48), (0.32, 0.66, 1.0), (1.0, 0.68, 0.26)]


class Ld2450(Node):
    def __init__(self):
        super().__init__("ld2450")
        self.url = self.declare_parameter("url", "http://127.0.0.1:8077/events").value
        self.frame_id = self.declare_parameter("frame_id", "radar").value
        # The panel draws +x to the right; ROS y points left, so y_ros = -x_sensor (flip with x_sign if wrong).
        self.x_sign = float(self.declare_parameter("x_sign", -1.0).value)
        self.pub_t = self.create_publisher(RadarTargets, "radar/targets", 10)
        self.pub_p = self.create_publisher(PointCloud2, "radar/points", 10)
        self.pub_m = self.create_publisher(MarkerArray, "radar/markers", 10)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while rclpy.ok():
            try:
                with urllib.request.urlopen(self.url, timeout=30) as r:
                    self.get_logger().info(f"reading {self.url}")
                    for line in r:
                        if line.startswith(b"data:"):
                            try:
                                self._publish(json.loads(line[5:]))
                            except ValueError:
                                pass
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"radar service: {e}; retrying in 3 s", throttle_duration_sec=30)
            time.sleep(3)

    def _publish(self, m):
        h = Header(); h.stamp = self.get_clock().now().to_msg(); h.frame_id = self.frame_id
        out = RadarTargets(header=h, connected=bool(m.get("connected")), demo=bool(m.get("demo")), fps=float(m.get("fps") or 0),
                           frames=int(m.get("frames") or 0), bad=int(m.get("bad") or 0), error=str(m.get("error") or ""))
        pts = []
        for i, t in enumerate(m.get("targets") or []):
            if not t:
                continue
            x, y = t["x"] / 1000.0, t["y"] / 1000.0
            out.targets.append(RadarTarget(slot=i + 1, x_m=x, y_m=y, speed_mps=t["v"] / 100.0, distance_m=math.hypot(x, y),
                                           angle_deg=math.degrees(math.atan2(x, y)), resolution_m=t.get("res", 0) / 1000.0))
            pts.append((y, self.x_sign * x, 0.0))
        self.pub_t.publish(out)
        self.pub_p.publish(point_cloud2.create_cloud_xyz32(h, pts))
        self.pub_m.publish(self._markers(h, out))

    def _markers(self, h, out):
        ma = MarkerArray()
        fov = Marker(header=h, ns="fov", id=0, type=Marker.LINE_STRIP, action=Marker.ADD)
        fov.scale.x = 0.02; fov.color.r, fov.color.g, fov.color.b, fov.color.a = 0.2, 0.6, 0.35, 0.8; fov.pose.orientation.w = 1.0
        fov.points = [Point()] + [Point(x=6 * math.cos(math.radians(a)), y=6 * math.sin(math.radians(a))) for a in range(-60, 61, 5)] + [Point()]
        ma.markers.append(fov)
        for slot in (1, 2, 3):
            t = next((t for t in out.targets if t.slot == slot), None)
            for ns, typ in (("target", Marker.SPHERE), ("label", Marker.TEXT_VIEW_FACING)):
                mk = Marker(header=h, ns=ns, id=slot, type=typ, action=Marker.ADD if t else Marker.DELETE)
                if t:
                    mk.pose.position.x, mk.pose.position.y = float(t.y_m), self.x_sign * float(t.x_m)
                    mk.pose.position.z = 0.0 if ns == "target" else 0.35
                    mk.pose.orientation.w = 1.0
                    r, g, b = COLORS[slot - 1]
                    mk.color.r, mk.color.g, mk.color.b, mk.color.a = r, g, b, 1.0
                    if ns == "target":
                        mk.scale.x = mk.scale.y = mk.scale.z = 0.25
                    else:
                        mk.scale.z = 0.2; mk.text = f"T{slot} {t.distance_m:.2f} m {t.angle_deg:+.0f}° {t.speed_mps:+.2f} m/s"
                ma.markers.append(mk)
        return ma


def main():
    rclpy.init(); n = Ld2450()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
