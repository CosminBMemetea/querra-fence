"""Ground robot bridge: the Gazebo robot on the Mac (tools/ugv_relay.py, TCP) -> ROS 2 topics, and /ugv/cmd_vel back.

Frames: ugv_map is the simulation's world frame (east, north; origin = forest.json "origin"), ugv_odom is where the
wheel odometry starts (the spawn pose, a static ugv_map -> ugv_odom), ugv_base_link is the robot, with static
ugv_lidar, ugv_camera_optical and ugv_imu from the robot's sensor mounts in the meta message.

Robot topics (what a real robot would have):
  /ugv/lidar/points                sensor_msgs/PointCloud2 (x, y, z, ring) in ugv_lidar, 10 Hz
  /ugv/imu                         sensor_msgs/Imu, 50 Hz
  /ugv/odom                        nav_msgs/Odometry ugv_odom -> ugv_base_link (wheel odometry) + TF
  /ugv/odom_map                    the same pose in ugv_map (dead reckoning from the spawn pose): ugv_patrol's default
  /ugv/gps/fix, /ugv/gps/info      NavSatFix (eph-based covariance) and GpsInfo, degraded under the tree crowns
  /ugv/camera/image_raw/compressed JPEG from the side camera, looking at the fence
  /ugv/route                       nav_msgs/Path in ugv_map (latched): the taught patrol route
  /ugv/fence                       visualization_msgs/MarkerArray (latched): fence line and posts
Scoring topics (ground truth from the simulator; never used for driving unless ugv_patrol is told to):
  /ugv/ground_truth                nav_msgs/Odometry in ugv_map
  /ugv/trail/truth, /ugv/trail/odom  nav_msgs/Path: where the robot really went and where odometry thinks it went
  /ugv/eval/odom_drift_m, /ugv/eval/gps_error_m  std_msgs/Float32
  /ugv/faults                      MarkerArray (latched): the seeded faults
In:  /ugv/cmd_vel (geometry_msgs/Twist), /ugv/reset (std_msgs/Empty: back to the spawn pose, odometry zeroed),
     /ugv/patrol/status (forwarded to the relay's log, so a patrol can be scored from one file).
"""
import json, math, socket, struct, threading, time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from geometry_msgs.msg import Twist, TransformStamped, PoseStamped, Point
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import PointCloud2, PointField, Imu, NavSatFix, NavSatStatus, CompressedImage
from std_msgs.msg import Empty, Float32, String, ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
from querra_fence_msgs.msg import GpsInfo

MAGIC = b"QUG1"
LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)


def quat(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = (math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2),
                              math.cos(yaw / 2), math.sin(yaw / 2))
    return (sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy)


def m_per_deg(lat0):
    p = math.radians(lat0)
    return (111132.954 - 559.822 * math.cos(2 * p) + 1.175 * math.cos(4 * p),
            111412.84 * math.cos(p) - 93.5 * math.cos(3 * p))


class UgvBridge(Node):
    def __init__(self):
        super().__init__("ugv_bridge")
        self.source = self.declare_parameter("source", "tcp://127.0.0.1:5611").value
        self.trail_step = float(self.declare_parameter("trail_step_m", 0.5).value)
        p = lambda t, T, q=10: self.create_publisher(T, t, q)
        self.pub = {
            "cloud": p("/ugv/lidar/points", PointCloud2, qos_profile_sensor_data), "imu": p("/ugv/imu", Imu, 50),
            "odom": p("/ugv/odom", Odometry), "odom_map": p("/ugv/odom_map", Odometry), "fix": p("/ugv/gps/fix", NavSatFix),
            "info": p("/ugv/gps/info", GpsInfo), "cam": p("/ugv/camera/image_raw/compressed", CompressedImage, qos_profile_sensor_data),
            "truth": p("/ugv/ground_truth", Odometry), "trail_truth": p("/ugv/trail/truth", Path), "trail_odom": p("/ugv/trail/odom", Path),
            "drift": p("/ugv/eval/odom_drift_m", Float32), "gps_err": p("/ugv/eval/gps_error_m", Float32),
            "route": p("/ugv/route", Path, LATCHED), "fence": p("/ugv/fence", MarkerArray, LATCHED),
            "faults": p("/ugv/faults", MarkerArray, LATCHED),
        }
        self.tf = TransformBroadcaster(self)
        self.static_tf = StaticTransformBroadcaster(self)
        self.create_subscription(Twist, "/ugv/cmd_vel", self.on_cmd, 10)
        self.create_subscription(Empty, "/ugv/reset", lambda _: self.send({"reset": True}), 10)
        self.create_subscription(String, "/ugv/patrol/status", self.on_status, 10)
        self.sock, self.sock_lock = None, threading.Lock()
        self.meta, self.spawn = None, (0.0, 0.0, 0.0)
        self.truth, self.odom_map = None, None
        self.trails = {"truth": Path(), "odom": Path()}
        self.dirs = None
        self.last_status = None
        threading.Thread(target=self.loop, daemon=True).start()

    # ---------------------------------------------------------------- link
    def send(self, obj):
        with self.sock_lock:
            if self.sock is None:
                return
            try:
                self.sock.sendall((json.dumps(obj) + "\n").encode())
            except OSError:
                pass

    def on_cmd(self, m):
        self.send({"cmd_vel": [m.linear.x, m.angular.z]})

    def on_status(self, m):
        try:
            st = json.loads(m.data)
        except ValueError:
            return
        key = (st.get("state"), st.get("pose_topic"))
        if key != self.last_status:                          # state changes only
            self.last_status = key
            self.send({"event": dict(st, src="patrol")})

    def loop(self):
        host, port = self.source.replace("tcp://", "").rsplit(":", 1)
        while rclpy.ok():
            try:
                s = socket.create_connection((host, int(port)), timeout=5)
                s.settimeout(10)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self.sock_lock:
                    self.sock = s
                self.get_logger().info(f"connected to the robot at {self.source}")
                f = s.makefile("rb")
                while rclpy.ok():
                    hdr = f.read(13)
                    if len(hdr) < 13 or hdr[:4] != MAGIC:
                        raise OSError("stream lost")
                    kind = chr(hdr[4])
                    hl, pl = struct.unpack(">II", hdr[5:13])
                    h = json.loads(f.read(hl))
                    payload = f.read(pl) if pl else b""
                    try:
                        self.dispatch(kind, h, payload)
                    except Exception as e:                   # one bad message must not kill the link
                        self.get_logger().error(f"message {kind}: {e!r}", throttle_duration_sec=10)
            except (OSError, ValueError) as e:
                self.get_logger().warn(f"robot link {self.source}: {e}; retrying in 2 s", throttle_duration_sec=20)
            with self.sock_lock:
                self.sock = None
            time.sleep(2)

    # ---------------------------------------------------------------- messages
    def stamp(self):
        return self.get_clock().now().to_msg()

    def dispatch(self, kind, h, payload):
        if kind == "M":
            self.on_meta(h)
        elif self.meta is None:
            return
        elif kind == "L":
            self.on_lidar(h, payload)
        elif kind == "C":
            m = CompressedImage(format="jpeg", data=payload)
            m.header.stamp, m.header.frame_id = self.stamp(), "ugv_camera_optical"
            self.pub["cam"].publish(m)
        elif kind == "I":
            self.on_imu(h)
        elif kind == "O":
            self.on_odom(h)
        elif kind == "T":
            self.on_truth(h)
        elif kind == "G":
            self.on_gps(h)

    def on_meta(self, meta):
        self.meta = meta
        self.spawn = tuple(meta["spawn"])
        self.lat0, self.lon0 = meta["origin"]["lat"], meta["origin"]["lon"]
        self.mlat, self.mlon = m_per_deg(self.lat0)
        stamp = self.stamp()
        tfs = [self.make_tf(stamp, "ugv_map", "ugv_odom", self.spawn[0], self.spawn[1], 0.0, 0.0, 0.0, self.spawn[2])]
        R = meta["robot"]
        bz = R["base_z"]
        for child, key in (("ugv_lidar", "lidar"), ("ugv_imu", "imu")):
            x, y, z = R[key]["xyz"]
            r, pch, yw = R[key]["rpy"]
            tfs.append(self.make_tf(stamp, "ugv_base_link", child, x, y, z + bz, r, pch, yw))
        # camera: the sensor looks along +x in its frame; the optical frame looks along +z (x right, y down)
        x, y, z = R["camera"]["xyz"]
        r, pch, yw = R["camera"]["rpy"]
        tfs.append(self.make_tf(stamp, "ugv_base_link", "ugv_camera", x, y, z + bz, r, pch, yw))
        tfs.append(self.make_tf(stamp, "ugv_camera", "ugv_camera_optical", 0, 0, 0, -math.pi / 2, 0, -math.pi / 2))
        self.static_tf.sendTransform(tfs)
        path = Path()
        path.header.stamp, path.header.frame_id = stamp, "ugv_map"
        for x, y in meta["route"]:
            ps = PoseStamped()
            ps.header = path.header
            ps.pose.position.x, ps.pose.position.y = float(x), float(y)
            ps.pose.orientation.w = 1.0
            path.poses.append(ps)
        self.pub["route"].publish(path)
        self.pub["fence"].publish(self.fence_markers(meta, stamp))
        self.pub["faults"].publish(self.fault_markers(meta, stamp))
        self.trails = {"truth": Path(), "odom": Path()}
        self.last_status = None                              # a new relay log gets the current patrol state once
        self.get_logger().info(f"robot meta: world {meta['world']}, route {meta['route_length_m']} m, "
                               f"{len(meta['faults'])} faults, spawn {self.spawn}")

    def make_tf(self, stamp, parent, child, x, y, z, r, p, yw):
        t = TransformStamped()
        t.header.stamp, t.header.frame_id, t.child_frame_id = stamp, parent, child
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = float(x), float(y), float(z)
        q = quat(r, p, yw)
        t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = q
        return t

    def fence_markers(self, meta, stamp):
        arr = MarkerArray()
        line = Marker(ns="fence", id=0, type=Marker.LINE_STRIP, action=Marker.ADD)
        line.header.stamp, line.header.frame_id = stamp, "ugv_map"
        line.scale.x = 0.06
        line.color = ColorRGBA(r=0.95, g=0.8, b=0.2, a=1.0)
        line.pose.orientation.w = 1.0
        posts = meta.get("fence_posts", [])
        line.points = [Point(x=float(x), y=float(y), z=1.0) for x, y in posts + posts[:1]]
        arr.markers.append(line)
        dots = Marker(ns="fence", id=1, type=Marker.SPHERE_LIST, action=Marker.ADD)
        dots.header = line.header
        dots.scale.x = dots.scale.y = dots.scale.z = 0.15
        dots.color = ColorRGBA(r=0.45, g=0.32, b=0.2, a=1.0)
        dots.pose.orientation.w = 1.0
        dots.points = [Point(x=float(x), y=float(y), z=0.6) for x, y in posts]
        arr.markers.append(dots)
        return arr

    def fault_markers(self, meta, stamp):
        arr = MarkerArray()
        for i, ft in enumerate(meta["faults"]):
            for k, (typ, z, scale) in enumerate(((Marker.SPHERE, 0.8, 0.6), (Marker.TEXT_VIEW_FACING, 2.2, 0.7))):
                m = Marker(ns="faults", id=i * 2 + k, type=typ, action=Marker.ADD)
                m.header.stamp, m.header.frame_id = stamp, "ugv_map"
                m.pose.position.x, m.pose.position.y, m.pose.position.z = float(ft["x"]), float(ft["y"]), z
                m.pose.orientation.w = 1.0
                m.scale.x = m.scale.y = m.scale.z = scale
                m.color = ColorRGBA(r=1.0, g=0.25, b=0.15, a=0.6 if k == 0 else 1.0)
                if typ == Marker.TEXT_VIEW_FACING:
                    m.text = f"{ft['id']} {ft['type']}"
                arr.markers.append(m)
        return arr

    def on_lidar(self, h, payload):
        n, nv = h["count"], h["vcount"]
        key = (n, nv, h["angle_min"], h["angle_step"], h["vangle_min"], h["vangle_step"])
        if self.dirs is None or self.dirs[0] != key:
            ha = h["angle_min"] + np.arange(n) * h["angle_step"]
            va = h["vangle_min"] + np.arange(nv) * h["vangle_step"]
            cv = np.cos(va)[:, None]
            d = np.stack([cv * np.cos(ha)[None, :], cv * np.sin(ha)[None, :], np.repeat(np.sin(va)[:, None], n, 1)], -1)
            ring = np.repeat(np.arange(nv, dtype=np.float32)[:, None], n, 1)
            self.dirs = (key, d.reshape(-1, 3).astype(np.float32), ring.reshape(-1))
        r = np.frombuffer(payload, dtype=np.float16).astype(np.float32)
        ok = np.isfinite(r) & (r > h["range_min"]) & (r < h["range_max"])
        pts = self.dirs[1][ok] * r[ok, None]
        data = np.column_stack([pts, self.dirs[2][ok]]).astype(np.float32)
        m = PointCloud2()
        m.header.stamp, m.header.frame_id = self.stamp(), "ugv_lidar"
        m.height, m.width = 1, data.shape[0]
        m.fields = [PointField(name=nm, offset=4 * i, datatype=PointField.FLOAT32, count=1) for i, nm in enumerate(("x", "y", "z", "ring"))]
        m.is_bigendian, m.point_step, m.row_step, m.is_dense = False, 16, 16 * data.shape[0], True
        m.data = data.tobytes()
        self.pub["cloud"].publish(m)

    def on_imu(self, h):
        m = Imu()
        m.header.stamp, m.header.frame_id = self.stamp(), "ugv_imu"
        m.orientation.x, m.orientation.y, m.orientation.z, m.orientation.w = h["q"]
        m.angular_velocity.x, m.angular_velocity.y, m.angular_velocity.z = h["w"]
        m.linear_acceleration.x, m.linear_acceleration.y, m.linear_acceleration.z = h["a"]
        m.orientation_covariance = [1e-3, 0.0, 0.0, 0.0, 1e-3, 0.0, 0.0, 0.0, 1e-2]
        m.angular_velocity_covariance = [1e-5, 0.0, 0.0, 0.0, 1e-5, 0.0, 0.0, 0.0, 1e-5]
        m.linear_acceleration_covariance = [1e-3, 0.0, 0.0, 0.0, 1e-3, 0.0, 0.0, 0.0, 1e-3]
        self.pub["imu"].publish(m)

    def odom_msg(self, stamp, frame, child, x, y, yaw, v=0.0, w=0.0):
        m = Odometry()
        m.header.stamp, m.header.frame_id, m.child_frame_id = stamp, frame, child
        m.pose.pose.position.x, m.pose.pose.position.y = float(x), float(y)
        q = quat(0, 0, yaw)
        m.pose.pose.orientation.x, m.pose.pose.orientation.y, m.pose.pose.orientation.z, m.pose.pose.orientation.w = q
        m.twist.twist.linear.x, m.twist.twist.angular.z = float(v), float(w)
        return m

    def on_odom(self, h):
        stamp = self.stamp()
        self.pub["odom"].publish(self.odom_msg(stamp, "ugv_odom", "ugv_base_link", h["x"], h["y"], h["yaw"], h["v"], h["w"]))
        self.tf.sendTransform(self.make_tf(stamp, "ugv_odom", "ugv_base_link", h["x"], h["y"], 0.0, 0, 0, h["yaw"]))
        sx, sy, syaw = self.spawn
        c, s = math.cos(syaw), math.sin(syaw)
        mx, my, myaw = sx + c * h["x"] - s * h["y"], sy + s * h["x"] + c * h["y"], syaw + h["yaw"]
        self.odom_map = (mx, my, myaw)
        self.pub["odom_map"].publish(self.odom_msg(stamp, "ugv_map", "ugv_base_link_dr", mx, my, myaw, h["v"], h["w"]))
        self.add_trail("odom", stamp, mx, my)
        if self.truth:
            d = Float32(data=float(math.hypot(mx - self.truth[0], my - self.truth[1])))
            self.pub["drift"].publish(d)

    def on_truth(self, h):
        stamp = self.stamp()
        self.truth = (h["x"], h["y"], h["yaw"])
        self.pub["truth"].publish(self.odom_msg(stamp, "ugv_map", "ugv_truth", h["x"], h["y"], h["yaw"]))
        self.add_trail("truth", stamp, h["x"], h["y"])

    def add_trail(self, key, stamp, x, y):
        tr = self.trails[key]
        if tr.poses:
            last = tr.poses[-1].pose.position
            if math.hypot(x - last.x, y - last.y) < self.trail_step:
                return
        ps = PoseStamped()
        ps.header.stamp, ps.header.frame_id = stamp, "ugv_map"
        ps.pose.position.x, ps.pose.position.y, ps.pose.position.z = float(x), float(y), 0.05
        ps.pose.orientation.w = 1.0
        tr.poses.append(ps)
        if len(tr.poses) > 4000:
            del tr.poses[:1000]
        tr.header.stamp, tr.header.frame_id = stamp, "ugv_map"
        self.pub["trail_" + key].publish(tr)

    def on_gps(self, h):
        stamp = self.stamp()
        mode = int(h.get("mode", 0))
        f = NavSatFix()
        f.header.stamp, f.header.frame_id = stamp, "ugv_base_link"
        f.status.status = NavSatStatus.STATUS_FIX if mode >= 2 else NavSatStatus.STATUS_NO_FIX
        f.status.service = NavSatStatus.SERVICE_GPS | NavSatStatus.SERVICE_GLONASS
        if mode >= 2:
            f.latitude, f.longitude, f.altitude = h["lat"], h["lon"], h["alt"]
            e2 = float(h.get("eph", 5.0)) ** 2
            f.position_covariance = [e2, 0.0, 0.0, 0.0, e2, 0.0, 0.0, 0.0, 4 * e2]
            f.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
            if self.truth:
                ex = (h["lon"] - self.lon0) * self.mlon - self.truth[0]
                ey = (h["lat"] - self.lat0) * self.mlat - self.truth[1]
                self.pub["gps_err"].publish(Float32(data=float(math.hypot(ex, ey))))
        else:
            f.latitude = f.longitude = f.altitude = float("nan")
            f.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        self.pub["fix"].publish(f)
        i = GpsInfo()
        i.header = f.header
        i.mode, i.fix = mode, {2: "2D", 3: "3D"}.get(mode, "none")
        i.sats_used = i.sats_seen = int(h.get("sats", 0))
        i.hdop, i.speed_mps, i.track_deg = float(h.get("eph", float("nan"))) / 2.5, float("nan"), float("nan")
        i.fix_age_s = 0.0 if mode >= 2 else float("nan")
        i.device = "sim:canopy=%.2f" % h.get("cover", 0.0)
        self.pub["info"].publish(i)


def main():
    rclpy.init()
    n = UgvBridge()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
