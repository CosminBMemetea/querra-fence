"""Camera node: reads one camera from the QUERRA panel hub's MJPEG stream (the hub owns /dev/video* and Argus).

Publishes <name>/image_raw/compressed (sensor_msgs/CompressedImage, the hub's JPEG as is) and, if publish_raw is true,
<name>/image_raw (sensor_msgs/Image, bgr8) plus <name>/camera_info (frame size only, no calibration yet).
"""
import threading, time, urllib.request
import cv2, numpy as np, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image, CameraInfo


class HubCamera(Node):
    def __init__(self):
        super().__init__("hub_camera")
        self.cam = self.declare_parameter("camera", "usb").value
        self.url = self.declare_parameter("url", f"http://127.0.0.1:8080/stream/{self.cam}.mjpg").value
        self.frame_id = self.declare_parameter("frame_id", f"{self.cam}_camera_optical").value
        self.publish_raw = self.declare_parameter("publish_raw", True).value
        self.pub_c = self.create_publisher(CompressedImage, "image_raw/compressed", qos_profile_sensor_data)
        self.pub_r = self.create_publisher(Image, "image_raw", qos_profile_sensor_data)
        self.pub_i = self.create_publisher(CameraInfo, "camera_info", qos_profile_sensor_data)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while rclpy.ok():
            try:
                with urllib.request.urlopen(self.url, timeout=10) as r:
                    self.get_logger().info(f"reading {self.url}")
                    self._read(r)
            except Exception as e:  # noqa: BLE001  hub restarting or camera taken by the Vision demo
                self.get_logger().warn(f"{self.url}: {e}; retrying in 3 s", throttle_duration_sec=30)
            time.sleep(3)

    def _read(self, r):
        while rclpy.ok():
            line = r.readline()
            if not line:
                return
            if not line.lower().startswith(b"content-length:"):
                continue
            n = int(line.split(b":")[1])
            while r.readline() not in (b"\r\n", b"\n"):
                pass
            self._publish(r.read(n))

    def _publish(self, jpeg):
        stamp = self.get_clock().now().to_msg()
        m = CompressedImage(format="jpeg", data=jpeg); m.header.stamp = stamp; m.header.frame_id = self.frame_id
        self.pub_c.publish(m)
        # Decoding costs CPU on the Jetson: only when someone subscribes to the raw image (viewer, bag, detector).
        if not self.publish_raw or (self.pub_r.get_subscription_count() == 0 and self.pub_i.get_subscription_count() == 0):
            return
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return
        h, w = img.shape[:2]
        im = Image(height=h, width=w, encoding="bgr8", is_bigendian=0, step=w * 3, data=img.tobytes())
        im.header.stamp = stamp; im.header.frame_id = self.frame_id
        self.pub_r.publish(im)
        ci = CameraInfo(height=h, width=w); ci.header = im.header
        self.pub_i.publish(ci)


def main():
    rclpy.init(); n = HubCamera()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
