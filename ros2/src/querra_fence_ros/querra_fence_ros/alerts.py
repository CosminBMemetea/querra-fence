"""Alert confirmation node: a fault becomes an alert only when 5 of the last 8 detector frames saw it within 5 m
on the ground (conf >= 0.7), the same rule as tools/confirm.py and field mode.

Subscribes /detections and a Telemetry topic (sim: /sim/telemetry). Publishes /fence/alerts (FenceAlert, new and
updated), /fence/alerts/fix (NavSatFix per alert, for Foxglove's Map) and /fence/alerts/count.
"""
import math
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import NavSatFix, NavSatStatus
from std_msgs.msg import UInt32
from vision_msgs.msg import Detection2DArray
from querra_fence_msgs.msg import FenceAlert, Telemetry
from .confirm import AlertConfirmer


class Alerts(Node):
    def __init__(self):
        super().__init__("alert_confirm")
        p = lambda k, v: self.declare_parameter(k, v).value
        cam = {"img_w": p("img_w", 640), "img_h": p("img_h", 400), "fx": p("fx", 465.7), "pitch_deg": p("pitch_deg", 55.0)}
        self.c = AlertConfirmer(n=p("n", 5), m=p("m", 8), radius_m=p("radius_m", 5.0), conf=p("conf", 0.7), merge_m=p("merge_m", 10.0), cam=cam)
        self.tel = None
        latched = QoSProfile(depth=50, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub = self.create_publisher(FenceAlert, "/fence/alerts", latched)
        self.pub_fix = self.create_publisher(NavSatFix, "/fence/alerts/fix", latched)
        self.pub_n = self.create_publisher(UInt32, "/fence/alerts/count", latched)
        self.create_subscription(Telemetry, p("telemetry", "/sim/telemetry"), lambda m: setattr(self, "tel", m), 10)
        self.create_subscription(Detection2DArray, "/detections", self._on_dets, 10)
        self.pub_n.publish(UInt32(data=0))
        self.get_logger().info(f"confirm n={self.c.n} of m={self.c.m}, radius {self.c.radius} m, conf {self.c.conf}, camera {cam}")

    def _on_dets(self, msg):
        t = self.tel
        if t is None or math.isnan(t.latitude):
            return
        nan = lambda v: None if math.isnan(v) else v
        dets = [{"class": d.results[0].hypothesis.class_id, "conf": d.results[0].hypothesis.score,
                 "box_xyxy": [d.bbox.center.position.x - d.bbox.size_x / 2, d.bbox.center.position.y - d.bbox.size_y / 2,
                              d.bbox.center.position.x + d.bbox.size_x / 2, d.bbox.center.position.y + d.bbox.size_y / 2]}
                for d in msg.detections if d.results]
        before = {id(a): a["sightings"] for a in self.c.alerts}
        new = self.c.update(dets, t.latitude, t.longitude, nan(t.altitude_m), nan(t.heading_deg))
        for i, a in enumerate(self.c.alerts):
            fresh = any(a is b for b in new)
            if not fresh and before.get(id(a)) == a["sightings"]:
                continue
            m = FenceAlert(header=msg.header, id=i + 1, class_name=a["class"], latitude=a["lat"], longitude=a["lon"],
                           max_conf=float(a["max_conf"]), frames=a["frames"], sightings=a["sightings"], is_new=fresh)
            m.header.frame_id = "map"
            self.pub.publish(m)
            if fresh:
                f = NavSatFix(header=m.header, latitude=a["lat"], longitude=a["lon"], altitude=0.0)
                f.status.status = NavSatStatus.STATUS_FIX
                self.pub_fix.publish(f)
                self.get_logger().info(f"ALERT #{m.id} {a['class']} at {a['lat']:.6f},{a['lon']:.6f} conf {a['max_conf']} ({a['frames']} frames)")
        if new:
            self.pub_n.publish(UInt32(data=len(self.c.alerts)))


def main():
    rclpy.init(); n = Alerts()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
