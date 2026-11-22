"""Stats node: measures every QUERRA topic's rate and writes /ws/stats.json every 2 s for the panel's ROS 2 card.

Subscribes with raw=True (no deserialisation). It skips on-demand topics, whose publishers only do the work while
someone subscribes: */image_raw (the camera nodes' JPEG decode) and /detections/image (the detector's annotation and
JPEG encode). Measuring them would make that work run all the time.
"""
import json, os, time
from collections import deque
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from rosidl_runtime_py.utilities import get_message

SKIP = ("/parameter_events", "/rosout")
ON_DEMAND = ("/image_raw", "/camera_info", "/detections/image", "/lidar/points")   # name suffixes (the 3D cloud: heavy)


class Stats(Node):
    def __init__(self):
        super().__init__("querra_stats")
        self.path = self.declare_parameter("path", "/ws/stats.json").value
        # topic name prefixes not to measure (the ground robot's launch passes its high-rate and bulky ones)
        self.skip = tuple(p for p in self.declare_parameter("skip_prefixes", [""]).value if p)
        self.window = 5.0
        self.subs, self.stamps, self.types = {}, {}, {}
        self.started = time.time()
        # phase 2 summary for the panel: detector frames/boxes/latency and confirmed alerts
        self.p2 = {"frames": 0, "boxes": 0, "last_boxes": 0, "latency_ms": None, "alerts": 0, "last_alert": None}
        self.alerts = {}
        from std_msgs.msg import Float32
        from vision_msgs.msg import Detection2DArray
        from querra_fence_msgs.msg import FenceAlert
        self.create_subscription(Detection2DArray, "/detections", self._on_dets, 10)
        self.create_subscription(Float32, "/detections/latency_ms", lambda m: self.p2.update(latency_ms=round(m.data, 1)), 10)
        # /fence/alerts carries only confirmed alerts (updates go to /fence/alerts/updates), so last_alert is the latest one
        self.create_subscription(FenceAlert, "/fence/alerts", self._on_alert, QoSProfile(depth=200, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(3.0, self._discover)
        self.create_timer(2.0, self._write)
        self._discover()

    def _discover(self):
        for name, types in self.get_topic_names_and_types():
            if (name in self.subs or name in SKIP or name.startswith("/events/") or name.endswith(ON_DEMAND)
                    or (self.skip and name.startswith(self.skip))):
                continue
            try:
                cls = get_message(types[0])
            except (AttributeError, ModuleNotFoundError, ValueError):
                continue
            q = self.stamps.setdefault(name, deque(maxlen=400)); self.types[name] = types[0]
            self.subs[name] = self.create_subscription(cls, name, lambda _m, q=q: q.append(time.monotonic()), qos_profile_sensor_data, raw=True)

    def _on_dets(self, m):
        self.p2["frames"] += 1; self.p2["last_boxes"] = len(m.detections); self.p2["boxes"] += len(m.detections)

    def _on_alert(self, m):
        if not m.is_new:
            return
        self.alerts[m.id] = m.class_name
        self.p2.update(alerts=len(self.alerts), last_alert=f"#{m.id} {m.class_name} {m.max_conf:.2f} ({m.frames} frames)")

    def _write(self):
        now = time.monotonic()
        topics = {}
        for name, q in sorted(self.stamps.items()):
            recent = [t for t in q if now - t <= self.window]
            hz = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 2 and recent[-1] > recent[0] else 0.0
            topics[name] = {"type": self.types[name], "hz": round(hz, 2), "age_s": round(now - q[-1], 1) if q else None}
        nodes = sorted(f"{ns.rstrip('/')}/{n}" for n, ns in self.get_node_names_and_namespaces())
        data = {"t": time.time(), "uptime_s": round(time.time() - self.started), "nodes": nodes, "topics": topics, "phase2": self.p2}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)


def main():
    rclpy.init(); n = Stats()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
