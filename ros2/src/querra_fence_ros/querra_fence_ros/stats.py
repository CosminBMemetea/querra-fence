"""Stats node: measures every QUERRA topic's rate and writes /ws/stats.json every 2 s for the panel's ROS 2 card.

Subscribes with raw=True (no deserialisation) and skips */image_raw so it never triggers the camera nodes' JPEG decode.
"""
import json, os, time
from collections import deque
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message

SKIP = ("/parameter_events", "/rosout")


class Stats(Node):
    def __init__(self):
        super().__init__("querra_stats")
        self.path = self.declare_parameter("path", "/ws/stats.json").value
        self.window = 5.0
        self.subs, self.stamps, self.types = {}, {}, {}
        self.started = time.time()
        self.create_timer(3.0, self._discover)
        self.create_timer(2.0, self._write)
        self._discover()

    def _discover(self):
        for name, types in self.get_topic_names_and_types():
            if name in self.subs or name in SKIP or name.startswith("/events/") or name.endswith("/image_raw") or name.endswith("/camera_info"):
                continue
            try:
                cls = get_message(types[0])
            except (AttributeError, ModuleNotFoundError, ValueError):
                continue
            q = self.stamps.setdefault(name, deque(maxlen=400)); self.types[name] = types[0]
            self.subs[name] = self.create_subscription(cls, name, lambda _m, q=q: q.append(time.monotonic()), qos_profile_sensor_data, raw=True)

    def _write(self):
        now = time.monotonic()
        topics = {}
        for name, q in sorted(self.stamps.items()):
            recent = [t for t in q if now - t <= self.window]
            hz = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 2 and recent[-1] > recent[0] else 0.0
            topics[name] = {"type": self.types[name], "hz": round(hz, 2), "age_s": round(now - q[-1], 1) if q else None}
        nodes = sorted(f"{ns.rstrip('/')}/{n}" for n, ns in self.get_node_names_and_namespaces())
        data = {"t": time.time(), "uptime_s": round(time.time() - self.started), "nodes": nodes, "topics": topics}
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
