"""Phone alerts from the robot: each new fence alert goes to the phone with the camera frame that confirmed it, the
fault boxes drawn on it, and a map link (notify.py: the backends, the rate limit, the retries).

The alert's stamp is its camera frame's (alert_confirm and ugv_alerts keep the detections' header, the detector the
image's), so the node keeps the last few seconds of camera frames and detections and picks that frame. It reads the
camera's JPEGs as they are: the detector does no extra work for it.

Parameters:
  config      the settings file (/etc/querra/notify.json in the container, mounted by ros.sh from
              ~/.config/querra/notify.json on the host); without it the node logs that phone alerts are off
  source      who raised the alert, in the message: "drone" or "ground robot"
  image       the detector's camera topic (CompressedImage)
  detections  /detections
  announce    true: a message when the node starts, so you know the phone link works before the patrol

Subscribes /fence/alerts with a volatile subscription: only alerts raised after the start, so a restart does not
resend the latched history. Updates of known alerts (/fence/alerts/updates) are not sent.
"""
import collections
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from vision_msgs.msg import Detection2DArray
from querra_fence_msgs.msg import FenceAlert
from . import notify


def stamp(header):
    return header.stamp.sec + header.stamp.nanosec * 1e-9


def nearest(buf, t, tol):
    """The item of (stamp, item) pairs closest to t, if within tol seconds."""
    best = min(buf, key=lambda x: abs(x[0] - t), default=None)
    return best[1] if best is not None and abs(best[0] - t) <= tol else None


class PhoneAlerts(Node):
    def __init__(self):
        super().__init__("phone_alerts")
        p = lambda k, v: self.declare_parameter(k, v).value
        self.source = p("source", "drone")
        path = notify.config_path(p("config", "/etc/querra/notify.json"))
        cfg = notify.load_config(path)
        self.n = notify.Notifier(cfg, log=self.get_logger().warning) if cfg else None
        if not self.n or not self.n.backends:
            self.get_logger().warning("phone alerts off: no ntfy or Telegram settings in %s (tools/notify.py setup)" % path)
            self.n = None
            return
        self.images = collections.deque(maxlen=150)        # 10 s at 15 frames per second
        self.dets = collections.deque(maxlen=150)
        image = p("image", "/sim/camera/image_raw/compressed")
        self.create_subscription(CompressedImage, image, lambda m: self.images.append((stamp(m.header), m)),
                                 qos_profile_sensor_data)
        self.create_subscription(Detection2DArray, p("detections", "/detections"), self.on_dets, 10)
        self.create_subscription(FenceAlert, "/fence/alerts", self.on_alert, QoSProfile(depth=50))
        names = ", ".join(b.name for b in self.n.backends)
        self.get_logger().info("phone alerts on (%s): %s alerts, photos from %s" % (names, self.source, image))
        if p("announce", True):
            self.n.note("Querra fence", "Phone alerts on: the %s's fault alerts will arrive here." % self.source)

    def on_dets(self, m):
        boxes = [(d.results[0].hypothesis.class_id, d.results[0].hypothesis.score, d.bbox.center.position.x,
                  d.bbox.center.position.y, d.bbox.size_x, d.bbox.size_y) for d in m.detections if d.results]
        self.dets.append((stamp(m.header), boxes))

    def on_alert(self, m):
        if not m.is_new:
            return
        t = stamp(m.header)
        img = nearest(self.images, t, 0.5)
        jpeg = notify.annotate(bytes(img.data), nearest(self.dets, t, 0.05) or [], m.class_name) if img else None
        self.n.alert({"source": self.source, "class": m.class_name, "id": m.id, "conf": float(m.max_conf),
                      "frames": m.frames, "lat": m.latitude, "lon": m.longitude, "time": time.time()}, jpeg)
        self.get_logger().info("alert %d (%s) queued for the phone%s" % (m.id, m.class_name, "" if jpeg else ", no photo"))


def main():
    rclpy.init()
    n = PhoneAlerts()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        if n.n:
            n.n.close(timeout=5)
        n.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
