"""Patrol node: drives the ground robot along the taught route (/ugv/route, "teach and repeat") with pure pursuit.

- Pose: an Odometry topic in ugv_map, chosen with pose_topic. /ugv/odom_map (wheel odometry from the spawn pose,
  the default: what the robot really knows), /ugv/ground_truth (the simulator's truth: only to test the rest of the
  chain), or a localisation node's output later (SLAM, EKF with GNSS).
- Safety: stops while the LiDAR sees something in the robot's path (a box ahead of the bumper, 0.12-1.0 m above the
  ground) and slows down when something is further ahead. The 3D LiDAR sits 0.8 m up and its lowest beam points 15
  degrees down, so it cannot see a low obstacle (a log, a rock) closer than about 2 m: a real robot would add a
  tilted LiDAR or a depth camera for the near field.
- Corners: when the target is more than turn_in_place_deg off its heading, the skid steer stops and turns on the
  spot (overshooting a sharp corner at speed swings the robot out into whatever stands beside the strip). Turning on
  the spot is allowed while nothing is inside the circle the robot's corners sweep (rotate_radius_m).
- Gives up ("blocked") after blocked_timeout_s stopped in front of an obstacle.

Topics: in /ugv/route, the pose topic, /ugv/lidar/points, /ugv/patrol/cmd (std_msgs/String: start | stop | restart);
out /ugv/cmd_vel, /ugv/patrol/status (std_msgs/String, JSON, 1 Hz and on every state change), /ugv/patrol/target.
"""
import json, math, time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from geometry_msgs.msg import Twist, PointStamped
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Empty, String


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class UgvPatrol(Node):
    def __init__(self):
        super().__init__("ugv_patrol")
        P = lambda n, d: self.declare_parameter(n, d).value
        self.pose_topic = P("pose_topic", "/ugv/odom_map")
        self.speed = float(P("speed", 0.8))
        self.lookahead = float(P("lookahead_m", 1.4))
        self.autostart = bool(P("autostart", True))
        self.stop_dist = float(P("stop_dist_m", 1.2))
        self.slow_dist = float(P("slow_dist_m", 2.5))
        self.half_width = float(P("half_width_m", 0.42))
        self.lidar_x = float(P("lidar_x_m", 0.12))          # LiDAR ahead of the base_link origin
        self.lidar_z = float(P("lidar_height_m", 0.80))     # LiDAR above the ground
        self.front = float(P("front_m", 0.40))              # bumper ahead of the base_link origin
        self.blocked_timeout = float(P("blocked_timeout_s", 20.0))
        self.turn_in_place = math.radians(float(P("turn_in_place_deg", 35.0)))
        self.rotate_radius = float(P("rotate_radius_m", 0.62))  # the corners of a 0.80 x 0.72 m footprint sweep 0.54 m
        self.route, self.pose, self.pose_t = None, None, 0.0
        self.obstacle = (False, False, False)                # (stop, slow, nothing may even turn on the spot)
        self.state, self.idx, self.restart_at = "idle", 0, 0.0
        self.t_start = self.travelled = 0.0
        self.last_xy, self.blocked_since, self.stops = None, None, 0
        self.cmd_pub = self.create_publisher(Twist, "/ugv/cmd_vel", 10)
        self.status_pub = self.create_publisher(String, "/ugv/patrol/status", 10)
        self.target_pub = self.create_publisher(PointStamped, "/ugv/patrol/target", 10)
        self.reset_pub = self.create_publisher(Empty, "/ugv/reset", 10)
        self.create_subscription(Path, "/ugv/route", self.on_route, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(Odometry, self.pose_topic, self.on_pose, 10)
        self.create_subscription(PointCloud2, "/ugv/lidar/points", self.on_cloud, qos_profile_sensor_data)
        self.create_subscription(String, "/ugv/patrol/cmd", self.on_cmd, 10)
        self.create_timer(0.05, self.control)
        self.create_timer(1.0, self.publish_status)
        self.get_logger().info(f"patrol: pose from {self.pose_topic}, {self.speed} m/s, autostart {self.autostart}")

    # ---------------------------------------------------------------- inputs
    def on_route(self, m):
        self.route = np.array([[p.pose.position.x, p.pose.position.y] for p in m.poses])
        seg = np.linalg.norm(np.diff(self.route, axis=0), axis=1)
        self.route_s = np.concatenate([[0.0], np.cumsum(seg)])
        self.get_logger().info(f"route: {len(self.route)} points, {self.route_s[-1]:.0f} m")
        if self.autostart and self.state == "idle":
            self.start()

    def on_pose(self, m):
        p = m.pose.pose
        self.pose, self.pose_t = (p.position.x, p.position.y, yaw_of(p.orientation)), time.monotonic()
        if self.state == "driving" and self.last_xy is not None:
            self.travelled += math.hypot(p.position.x - self.last_xy[0], p.position.y - self.last_xy[1])
        self.last_xy = (p.position.x, p.position.y)

    def on_cloud(self, m):
        pts = np.frombuffer(m.data, dtype=np.float32).reshape(-1, m.point_step // 4)[:, :3]
        x = pts[:, 0] + self.lidar_x                         # base_link x (the LiDAR looks forward, no rotation)
        z = pts[:, 2] + self.lidar_z                         # height above the ground
        body = (np.abs(pts[:, 1]) < self.half_width) & (z > 0.12) & (z < 1.0)
        ahead = x - self.front
        band = (z > 0.12) & (z < 1.0)
        self.obstacle = (bool(np.any(body & (ahead > 0.0) & (ahead < self.stop_dist))),
                         bool(np.any(body & (ahead >= self.stop_dist) & (ahead < self.slow_dist))),
                         bool(np.any(band & (np.hypot(x, pts[:, 1]) < self.rotate_radius))))

    def on_cmd(self, m):
        c = m.data.strip().lower()
        if c == "start":
            self.start()
        elif c == "stop":
            self.set_state("stopped")
        elif c == "restart":                                 # back to the spawn pose, then a fresh patrol
            self.reset_pub.publish(Empty())
            self.restart_at = time.monotonic() + 3.0
            self.set_state("restarting")

    # ---------------------------------------------------------------- control
    def start(self):
        if self.route is None:
            return
        self.idx, self.travelled, self.stops, self.blocked_since = 0, 0.0, 0, None
        self.t_start = time.monotonic()
        self.last_xy = None
        self.set_state("driving")

    def set_state(self, s):
        if s != self.state:
            self.state = s
            self.get_logger().info(f"patrol: {s}")
            self.publish_status()
        if s in ("stopped", "done", "blocked", "idle", "restarting"):
            self.cmd_pub.publish(Twist())

    def control(self):
        if self.state == "restarting" and time.monotonic() >= self.restart_at:
            self.start()
        if self.state not in ("driving", "waiting") or self.route is None:
            return
        if self.pose is None or time.monotonic() - self.pose_t > 1.0:
            self.cmd_pub.publish(Twist())
            return
        x, y, yaw = self.pose
        R = self.route
        hi = min(len(R), self.idx + 60)                      # search forward only (the loop ends where it starts)
        d = np.hypot(R[self.idx:hi, 0] - x, R[self.idx:hi, 1] - y)
        self.idx += int(np.argmin(d))
        if self.idx >= len(R) - 2:
            self.set_state("done")
            return
        j = self.idx
        while j < len(R) - 1 and self.route_s[j] - self.route_s[self.idx] < self.lookahead:
            j += 1
        tx, ty = R[j]
        t = PointStamped()
        t.header.stamp, t.header.frame_id = self.get_clock().now().to_msg(), "ugv_map"
        t.point.x, t.point.y = float(tx), float(ty)
        self.target_pub.publish(t)
        c, s = math.cos(yaw), math.sin(yaw)
        xr, yr = c * (tx - x) + s * (ty - y), -s * (tx - x) + c * (ty - y)
        stop, slow, no_turn = self.obstacle
        cmd = Twist()
        alpha = math.atan2(yr, xr)                           # where the target is, from the robot's heading
        if abs(alpha) > self.turn_in_place and not no_turn:  # sharp corner: turn on the spot first
            self.blocked_since = None
            self.state = "driving"
            cmd.angular.z = math.copysign(0.6, alpha)
            self.cmd_pub.publish(cmd)
            return
        if stop or (abs(alpha) > self.turn_in_place and no_turn):
            if self.blocked_since is None:
                self.blocked_since = time.monotonic()
                self.stops += 1
            self.state = "waiting"
            if time.monotonic() - self.blocked_since > self.blocked_timeout:
                self.set_state("blocked")
                return
            self.cmd_pub.publish(cmd)
            return
        self.blocked_since = None
        self.state = "driving"
        k = 2.0 * yr / (xr * xr + yr * yr)                  # pure pursuit curvature
        v = self.speed / (1.0 + 2.0 * abs(k))
        v = max(0.25, min(self.speed, v)) * (0.5 if slow else 1.0)
        cmd.linear.x, cmd.angular.z = v, max(-1.0, min(1.0, k * v))
        self.cmd_pub.publish(cmd)

    def publish_status(self):
        if self.route is None:
            return
        total = float(self.route_s[-1])
        done_s = float(self.route_s[min(self.idx, len(self.route_s) - 1)])
        st = {"state": self.state, "pose_topic": self.pose_topic, "progress_pct": round(100 * done_s / total, 1),
              "along_route_m": round(done_s, 1), "route_m": round(total, 1), "travelled_m": round(self.travelled, 1),
              "elapsed_s": round(time.monotonic() - self.t_start, 1) if self.t_start else 0.0, "obstacle_stops": self.stops}
        self.status_pub.publish(String(data=json.dumps(st)))


def main():
    rclpy.init()
    n = UgvPatrol()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
