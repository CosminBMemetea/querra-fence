"""Ground robot alerts: a fault becomes an alert when the same fault class is seen in 5 of 8 frames taken 0.5 m of
travel apart, at spots within 5 m of each other on the fence. This is the rule tools/ground_patrol_eval.py scored
ground-v0.1 with offline, and the drone's alert_confirm logic, in metres.

A sighting counts from conf 0.7, and fallen posts from 0.5 (class_conf): ground-v0.1 scores fallen posts lower than
the other faults. On its held-out test forests, 0.7 kept 52% of the fallen posts and 0.5 kept 90%, with false fallen
posts in 0.5% of the frames (validation forests: 62% and 86%, 0.3%). At 0.7 the first live patrols missed F3.

Why frames by distance: the robot drives at 0.8 m/s and its camera runs at 10 Hz, so consecutive frames are 8 cm
apart. Counted directly, 5 of 8 frames would be 0.4 s, and a bush mistaken for a branch for half a second would
confirm. One frame per step_m of travel (the first after the robot has moved that far) makes 8 frames span 4 m of
route, as offline.

Each box is placed on the fence: the camera looks left, the fence is fence_offset_m to the side of the route, and
the box's horizontal position in the image gives the angle along the fence (camera hfov_deg wide). The robot's pose
is the patrol's (pose_topic: the SLAM pose with pose:=slam), so the alert is where the robot believes it is.

Subscribes /detections and pose_topic (nav_msgs/Odometry in ugv_map), /ugv/origin (the world's lat/lon origin, from
ugv_bridge). Publishes:
  /fence/alerts         FenceAlert per new alert (transient-local), position as latitude/longitude
  /ugv/alerts/event     String (JSON) per new alert, with x/y in ugv_map; ugv_bridge logs it on the Mac for scoring.
                        Also one line per 0.5 m step ("src": "step": the robot's position and its fault sightings),
                        so tools/ugv_eval.py can say how many steps near each fault showed it
  /ugv/alerts/markers   MarkerArray in ugv_map (transient-local): the alerts in Foxglove's 3D panel
"""
import collections
import json
import math

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import ColorRGBA, String
from vision_msgs.msg import Detection2DArray
from visualization_msgs.msg import Marker, MarkerArray
from querra_fence_msgs.msg import FenceAlert
from .ugv_bridge import m_per_deg

FAULTS = ("wire_break", "fallen_post", "branch")
LATCHED = QoSProfile(depth=200, durability=DurabilityPolicy.TRANSIENT_LOCAL)


class LocalConfirmer:
    """confirm.AlertConfirmer on a flat frame in metres: a sighting (class, conf, x, y) confirms when n of the last m
    frames hold one of its class within radius_m; sightings within merge_m of an existing alert only update it."""

    def __init__(self, n=5, m=8, radius_m=5.0, conf=0.7, merge_m=10.0, class_conf=None):
        self.n, self.m, self.radius, self.conf, self.merge = n, m, radius_m, conf, max(merge_m, radius_m)
        self.class_conf = class_conf or {}           # per-class thresholds that replace conf
        self.window = collections.deque(maxlen=m)
        self.alerts = []

    def update(self, sightings):
        frame = collections.defaultdict(list)
        for c, cf, x, y in sightings:
            if c in FAULTS and cf >= self.class_conf.get(c, self.conf):
                frame[c].append((x, y, cf))
        self.window.append(frame)
        new = []
        for cls, pts in frame.items():
            for x, y, cf in pts:
                old = next((a for a in self.alerts if a["class"] == cls and math.hypot(x - a["x"], y - a["y"]) <= self.merge), None)
                if old:
                    old["sightings"] += 1
                    old["max_conf"] = max(old["max_conf"], round(cf, 3))
                    continue
                hits = [next(((q[0], q[1]) for q in f.get(cls, ()) if math.hypot(x - q[0], y - q[1]) <= self.radius), None)
                        for f in self.window]
                hits = [h for h in hits if h]
                if len(hits) >= self.n:
                    a = {"id": len(self.alerts) + 1, "class": cls, "x": round(sum(h[0] for h in hits) / len(hits), 2),
                         "y": round(sum(h[1] for h in hits) / len(hits), 2), "frames": len(hits),
                         "max_conf": round(cf, 3), "sightings": len(hits)}
                    self.alerts.append(a)
                    new.append(a)
        return new


class UgvAlerts(Node):
    def __init__(self):
        super().__init__("ugv_alerts")
        p = lambda k, v: self.declare_parameter(k, v).value
        class_conf = {k.strip(): float(v) for k, v in (kv.split("=") for kv in p("class_conf", "fallen_post=0.5").split(",") if "=" in kv)}
        self.c = LocalConfirmer(p("n", 5), p("m", 8), p("radius_m", 5.0), p("conf", 0.7), p("merge_m", 10.0), class_conf)
        self.step = p("step_m", 0.5)
        self.offset = p("fence_offset_m", 1.9)           # route to fence
        self.cam_x, self.cam_y = p("camera_x", 0.0), p("camera_y", 0.22)   # camera mount on the robot (forest_meta.json)
        w, hfov = p("image_width", 640), math.radians(p("hfov_deg", 100.0))
        self.cx, self.fx, self.half = w / 2.0, (w / 2.0) / math.tan(hfov / 2.0), hfov / 2.0
        pose_topic = p("pose_topic", "/ugv/odom_map")
        self.pose, self.last_step, self.origin = None, None, None
        self.pub = self.create_publisher(FenceAlert, "/fence/alerts", LATCHED)
        self.pub_ev = self.create_publisher(String, "/ugv/alerts/event", 10)
        self.pub_mk = self.create_publisher(MarkerArray, "/ugv/alerts/markers", LATCHED)
        self.create_subscription(Odometry, pose_topic, self.on_pose, 10)
        self.create_subscription(NavSatFix, "/ugv/origin", lambda m: setattr(self, "origin", (m.latitude, m.longitude)),
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(Detection2DArray, "/detections", self.on_dets, 10)
        self.get_logger().info(f"confirm {self.c.n} of {self.c.m} frames {self.step} m apart, "
                               f"within {self.c.radius} m, conf {self.c.conf} {self.c.class_conf}; pose from {pose_topic}; fence {self.offset} m left")

    def on_pose(self, m):
        q = m.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self.pose = (m.pose.pose.position.x, m.pose.pose.position.y, yaw)

    def on_fence(self, u):
        """ugv_map position of the fence point seen at image column u."""
        x, y, yaw = self.pose
        a = max(-self.half, min(self.half, math.atan((u - self.cx) / self.fx)))   # > 0: right in the image = ahead
        along = self.cam_x + (self.offset - self.cam_y) * math.tan(a)
        c, s = math.cos(yaw), math.sin(yaw)
        return x + along * c - self.offset * s, y + along * s + self.offset * c

    def on_dets(self, msg):
        if self.pose is None:
            return
        x, y, _ = self.pose
        if self.last_step is not None and math.hypot(x - self.last_step[0], y - self.last_step[1]) < self.step:
            return
        self.last_step = (x, y)
        sightings = []
        for d in msg.detections:
            if d.results and d.results[0].hypothesis.class_id in FAULTS:
                fx, fy = self.on_fence(d.bbox.center.position.x)
                sightings.append((d.results[0].hypothesis.class_id, d.results[0].hypothesis.score, fx, fy))
        self.pub_ev.publish(String(data=json.dumps({"src": "step", "r": [round(x, 2), round(y, 2)],
                                                     "s": [[c, round(cf, 3), round(fx, 2), round(fy, 2)] for c, cf, fx, fy in sightings]})))
        for a in self.c.update(sightings):
            lat = lon = float("nan")
            if self.origin:
                mlat, mlon = m_per_deg(self.origin[0])
                lat, lon = self.origin[0] + a["y"] / mlat, self.origin[1] + a["x"] / mlon
            m = FenceAlert(header=msg.header, id=a["id"], class_name=a["class"], latitude=lat, longitude=lon,
                           max_conf=float(a["max_conf"]), frames=a["frames"], sightings=a["sightings"], is_new=True)
            m.header.frame_id = "ugv_map"
            self.pub.publish(m)
            st = msg.header.stamp
            self.pub_ev.publish(String(data=json.dumps(dict(a, stamp=round(st.sec + st.nanosec * 1e-9, 2),
                                                          robot=[round(x, 2), round(y, 2)]))))
            self.publish_markers(msg.header.stamp)
            self.get_logger().info(f"ALERT #{a['id']} {a['class']} at ({a['x']:.1f}, {a['y']:.1f}) conf {a['max_conf']} "
                                   f"({a['frames']} frames)")

    def publish_markers(self, stamp):
        arr = MarkerArray()
        for a in self.c.alerts:
            for k, (typ, z, scale) in enumerate(((Marker.CYLINDER, 1.2, 0.5), (Marker.TEXT_VIEW_FACING, 3.0, 0.6))):
                m = Marker(ns="alerts", id=a["id"] * 2 + k, type=typ, action=Marker.ADD)
                m.header.stamp, m.header.frame_id = stamp, "ugv_map"
                m.pose.position.x, m.pose.position.y, m.pose.position.z = float(a["x"]), float(a["y"]), z
                m.pose.orientation.w = 1.0
                m.scale.x = m.scale.y = scale
                m.scale.z = 2.4 if typ == Marker.CYLINDER else scale
                m.color = ColorRGBA(r=1.0, g=0.85, b=0.1, a=0.7 if k == 0 else 1.0)
                if typ == Marker.TEXT_VIEW_FACING:
                    m.text = f"alert {a['id']} {a['class']} {a['max_conf']:.2f}"
                arr.markers.append(m)
        self.pub_mk.publish(arr)


def main():
    rclpy.init()
    n = UgvAlerts()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
