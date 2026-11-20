"""PX4 pose node (phase 3): the drone's own position and heading from PX4 over uXRCE-DDS, as QUERRA Telemetry.

Subscribes the flight controller's topics, which the micro-ROS agent bridges from PX4's uXRCE-DDS client:
  /fmu/out/vehicle_global_position     lat, lon (EKF)
  /fmu/out/vehicle_local_position_v1   altitude above the EKF origin (-z), heading, ground speed
  /fmu/out/vehicle_status_v5           armed state and flight mode, used as the phase
Publishes /px4/telemetry (querra_fence_msgs/Telemetry, source "px4") for alert_confirm, and /px4/gps/fix
(NavSatFix) for Foxglove's map. PX4 publishes best-effort, so the subscriptions use the sensor-data QoS.
"""
import math
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import NavSatFix, NavSatStatus
from px4_msgs.msg import VehicleGlobalPosition, VehicleLocalPosition, VehicleStatus
from querra_fence_msgs.msg import Telemetry

NAN = float("nan")
PHASES = {VehicleStatus.NAVIGATION_STATE_AUTO_TAKEOFF: "takeoff", VehicleStatus.NAVIGATION_STATE_AUTO_MISSION: "inspection",
          VehicleStatus.NAVIGATION_STATE_AUTO_LOITER: "loiter", VehicleStatus.NAVIGATION_STATE_AUTO_RTL: "return",
          VehicleStatus.NAVIGATION_STATE_AUTO_LAND: "land", VehicleStatus.NAVIGATION_STATE_OFFBOARD: "offboard",
          VehicleStatus.NAVIGATION_STATE_POSCTL: "position", VehicleStatus.NAVIGATION_STATE_ALTCTL: "altitude",
          VehicleStatus.NAVIGATION_STATE_MANUAL: "manual"}


class Px4Pose(Node):
    def __init__(self):
        super().__init__("px4_pose")
        ns = self.declare_parameter("fmu_prefix", "/fmu/out").value.rstrip("/")
        self.max_hz = float(self.declare_parameter("max_hz", 20.0).value)
        self.glob = self.loc = None
        self.phase, self._last = "", 0.0
        self.pub = self.create_publisher(Telemetry, "/px4/telemetry", 10)
        self.pub_fix = self.create_publisher(NavSatFix, "/px4/gps/fix", 10)
        self.create_subscription(VehicleGlobalPosition, f"{ns}/vehicle_global_position", self._on_global, qos_profile_sensor_data)
        self.create_subscription(VehicleLocalPosition, f"{ns}/vehicle_local_position_v1", lambda m: setattr(self, "loc", m), qos_profile_sensor_data)
        self.create_subscription(VehicleStatus, f"{ns}/vehicle_status_v5", self._on_status, qos_profile_sensor_data)
        self.create_timer(5.0, self._check)
        self.get_logger().info(f"waiting for PX4 on {ns}/* (micro-ROS agent, UDP 8888)")

    def _on_status(self, m):
        armed = m.arming_state == VehicleStatus.ARMING_STATE_ARMED
        self.phase = PHASES.get(m.nav_state, f"mode_{m.nav_state}") if armed else "disarmed"

    def _check(self):
        if self.glob is None:
            self.get_logger().warn("no /fmu/out/vehicle_global_position yet: is PX4 running and the agent reachable?",
                                   throttle_duration_sec=30)

    def _on_global(self, g):
        first = self.glob is None
        self.glob = g
        if first:
            self.get_logger().info("PX4 connected: publishing /px4/telemetry")
        now = self.get_clock().now()
        if (now.nanoseconds - self._last) < 1e9 / self.max_hz:
            return
        self._last = now.nanoseconds
        loc, stamp = self.loc, now.to_msg()
        t = Telemetry(); t.header.stamp = stamp; t.header.frame_id = "base_link"
        t.latitude, t.longitude = (g.lat, g.lon) if g.lat_lon_valid else (NAN, NAN)
        t.altitude_m = float(-loc.z) if loc is not None and loc.z_valid else NAN
        t.heading_deg = float(math.degrees(loc.heading) % 360.0) if loc is not None and math.isfinite(loc.heading) else NAN
        t.speed_mps = float(math.hypot(loc.vx, loc.vy)) if loc is not None and loc.v_xy_valid else NAN
        t.phase, t.source = self.phase, "px4"
        self.pub.publish(t)
        f = NavSatFix(); f.header.stamp = stamp; f.header.frame_id = "gps"
        f.latitude, f.longitude, f.altitude = t.latitude, t.longitude, float(g.alt) if g.alt_valid else NAN
        f.status.status = NavSatStatus.STATUS_FIX if g.lat_lon_valid else NavSatStatus.STATUS_NO_FIX
        f.status.service = NavSatStatus.SERVICE_GPS
        if math.isfinite(g.eph) and math.isfinite(g.epv):
            f.position_covariance = [g.eph ** 2, 0.0, 0.0, 0.0, g.eph ** 2, 0.0, 0.0, 0.0, g.epv ** 2]
            f.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
        self.pub_fix.publish(f)


def main():
    rclpy.init(); n = Px4Pose()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
