"""Fence detector node: YOLO11n (model-v0.3) TensorRT FP16 engine on the Jetson GPU.

Subscribes image (CompressedImage, default /camera/usb/image_raw/compressed), always works on the newest frame,
publishes /detections (vision_msgs/Detection2DArray, same stamp as the image), /detections/image (annotated JPEG
for Foxglove) and /detections/latency_ms. The engine and querra_scout's YOLODetector are mounted from the host
(see ros.sh); TensorRT and CUDA come from JetPack, read-only.
"""
import threading, time
import cv2, numpy as np, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Float32
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

COLORS = {"wire_break": (60, 60, 255), "fallen_post": (255, 120, 60), "branch": (40, 200, 255), "post": (200, 200, 200),
          "wire": (120, 220, 120), "cow": (60, 170, 255), "sheep": (230, 230, 230)}
FAULTS = ("wire_break", "fallen_post", "branch")


class Detector(Node):
    def __init__(self):
        super().__init__("fence_detector")
        engine = self.declare_parameter("engine", "/models/fence-yolo11n-v0.3-fp16.engine").value
        self.conf = float(self.declare_parameter("conf", 0.35).value)
        topic = self.declare_parameter("image", "/camera/usb/image_raw/compressed").value
        from querra_scout.detector import YOLODetector
        self.det = YOLODetector(engine, conf=self.conf)
        self.get_logger().info(f"TensorRT engine {engine} {self.det.in_shape}, classes {self.det.classes}; input {topic}")
        self.pub = self.create_publisher(Detection2DArray, "/detections", 10)
        self.pub_img = self.create_publisher(CompressedImage, "/detections/image", qos_profile_sensor_data)
        self.pub_lat = self.create_publisher(Float32, "/detections/latency_ms", 10)
        self.latest, self.cv = None, threading.Condition()
        self.create_subscription(CompressedImage, topic, self._on_image, qos_profile_sensor_data)
        threading.Thread(target=self._worker, daemon=True).start()

    def _on_image(self, msg):
        with self.cv:
            self.latest = msg; self.cv.notify()

    def _worker(self):
        while rclpy.ok():
            with self.cv:
                self.cv.wait_for(lambda: self.latest is not None, timeout=1.0)
                msg, self.latest = self.latest, None
            if msg is None:
                continue
            t0 = time.perf_counter()
            bgr = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            dets, tm = self.det.detect(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            out = Detection2DArray(header=msg.header)
            for d in dets:
                x0, y0, x1, y1 = d["box_xyxy"]
                o = Detection2D(header=msg.header)
                o.bbox.center.position.x, o.bbox.center.position.y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                o.bbox.size_x, o.bbox.size_y = float(x1 - x0), float(y1 - y0)
                h = ObjectHypothesisWithPose(); h.hypothesis.class_id = d["class"]; h.hypothesis.score = float(d["conf"])
                o.results.append(h); out.detections.append(o)
            self.pub.publish(out)
            total = (time.perf_counter() - t0) * 1000.0
            self.pub_lat.publish(Float32(data=float(total)))
            if self.pub_img.get_subscription_count():
                self._annotate(bgr, dets, tm, total, msg.header)

    def _annotate(self, bgr, dets, tm, total, header):
        for d in dets:
            x0, y0, x1, y1 = [int(v) for v in d["box_xyxy"]]
            c = COLORS.get(d["class"], (255, 255, 255)); th = 3 if d["class"] in FAULTS else 2
            cv2.rectangle(bgr, (x0, y0), (x1, y1), c, th)
            label = f"{d['class']} {d['conf']:.2f}"
            (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(bgr, (x0, max(0, y0 - tht - 6)), (x0 + tw + 6, y0), c, -1)
            cv2.putText(bgr, label, (x0 + 3, y0 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        txt = f"YOLO11n v0.3 TensorRT FP16  infer {tm.get('det_infer_ms', 0):.1f} ms  total {total:.1f} ms  {len(dets)} det"
        cv2.rectangle(bgr, (0, bgr.shape[0] - 22), (bgr.shape[1], bgr.shape[0]), (0, 0, 0), -1)
        cv2.putText(bgr, txt, (6, bgr.shape[0] - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        m = CompressedImage(header=header, format="jpeg", data=cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes())
        self.pub_img.publish(m)


def main():
    rclpy.init(); n = Detector()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
