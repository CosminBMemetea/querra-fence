"""Re-fly node (phase 3, part 2): after the inspection loop, fly back low over every confirmed fault for a close look.

Trigger: PX4 enters Return (AUTO_RTL) while armed, at the end of the inspection mission, and there are confirmed
alerts on /fence/alerts (their positions kept up to date from /fence/alerts/updates). The node then:
  1. streams OffboardControlMode + TrajectorySetpoint (10 Hz) holding the current position, then asks PX4 for OFFBOARD;
  2. visits the alerts nearest-first: it descends to `altitude_m`, stops `standoff` metres before the fault (the
     inspection camera looks forward-down at `pitch_deg`, so the fault is in the middle of the frame) and faces it;
  3. hovers `hover_s` seconds and counts detector frames of the alert's class: verified when most of the hover frames
     (at least `verify_ratio` of them, and at least `min_frames` frames) see it at `min_conf` or more;
  4. sends Return (RTL); PX4 flies home and lands, and sim/mission.py finishes its report as usual.
The setpoint moves towards each target at `speed_mps` (a "carrot"), so the flight stays smooth.
Results: /fence/refly/status (std_msgs/String, JSON), /fence/refly/report (JSON, at the end) and the log.
Simulation first: enable with refly:=true (needs px4:=true). It only acts during the Return after a mission.
"""
import json, math, time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray
from px4_msgs.msg import OffboardControlMode, TrajectorySetpoint, VehicleCommand, VehicleLocalPosition, VehicleStatus
from querra_fence_msgs.msg import FenceAlert

NAN = float("nan")
FAULTS = ("wire_break", "fallen_post", "branch")
M_LAT = 111132.92
M_LON = 111319.49


class Refly(Node):
    def __init__(self):
        super().__init__("fence_refly")
        p = lambda k, v: self.declare_parameter(k, v).value
        self.alt = float(p("altitude_m", 6.0))
        self.pitch = math.radians(float(p("pitch_deg", 55.0)))
        self.standoff = self.alt / math.tan(self.pitch)               # where the camera's centre ray meets the ground
        self.hover_s = float(p("hover_s", 5.0))
        self.speed = float(p("speed_mps", 4.0))
        self.vspeed = float(p("vspeed_mps", 1.5))
        self.arrive_m = float(p("arrive_m", 1.0))
        self.max_targets = int(p("max_targets", 8))
        # Majority rule, chosen after the first SITL flight (2026-11-20): "3 frames" let 3 of 4 false alerts through,
        # a majority would have rejected all 4 and kept 2 of 4 real faults. One flight only: not a validated rule.
        self.verify_ratio = float(p("verify_ratio", 0.5))
        self.min_frames = int(p("min_frames", 10))
        self.min_conf = float(p("min_conf", 0.5))
        self.sysid = int(p("target_system", 1))

        px4_in = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                            history=HistoryPolicy.KEEP_LAST, depth=1)
        self.pub_mode = self.create_publisher(OffboardControlMode, "/fmu/in/offboard_control_mode", px4_in)
        self.pub_sp = self.create_publisher(TrajectorySetpoint, "/fmu/in/trajectory_setpoint", px4_in)
        self.pub_cmd = self.create_publisher(VehicleCommand, "/fmu/in/vehicle_command_v1", px4_in)
        self.pub_status = self.create_publisher(String, "/fence/refly/status", 10)
        self.pub_report = self.create_publisher(String, "/fence/refly/report",
                                                QoSProfile(depth=5, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(VehicleLocalPosition, "/fmu/out/vehicle_local_position_v1", self._on_loc, qos_profile_sensor_data)
        self.create_subscription(VehicleStatus, "/fmu/out/vehicle_status_v5", self._on_status, qos_profile_sensor_data)
        self.create_subscription(FenceAlert, "/fence/alerts", self._on_alert,
                                 QoSProfile(depth=200, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(FenceAlert, "/fence/alerts/updates", self._on_update, 10)
        self.create_subscription(Detection2DArray, "/detections", self._on_dets, 10)
        self.loc = self.status = None
        self.alerts = {}                 # id -> FenceAlert
        self.state, self.done_flight = "idle", False
        self.plan, self.cur, self.results = [], None, []
        self.sp = None                   # current carrot [n, e, d]
        self.t_state = time.monotonic()
        self.hover_hits, self.hover_frames, self.hover_best = 0, 0, 0.0
        self.create_timer(0.1, self._tick)
        self.get_logger().info(f"re-fly armed: after the mission, visit confirmed alerts at {self.alt:.0f} m, "
                               f"{self.standoff:.1f} m stand-off, {self.hover_s:.0f} s each")

    # ---------------- inputs ----------------
    def _on_loc(self, m):
        self.loc = m

    def _on_status(self, m):
        self.status = m
        if m.arming_state != VehicleStatus.ARMING_STATE_ARMED and self.state in ("idle", "finished", "aborted"):
            if self.state != "idle":
                self.get_logger().info("re-fly: landed and disarmed, ready for the next flight")
            self.state, self.done_flight, self.results = "idle", False, []

    def _on_alert(self, a):
        if a.is_new and a.class_name in FAULTS:
            self.alerts[a.id] = a

    def _on_update(self, a):
        if a.id in self.alerts:          # a known alert seen again: its position, refined with every sighting
            self.alerts[a.id] = a

    def _on_dets(self, m):
        if self.state != "hover" or self.cur is None:
            return
        self.hover_frames += 1
        cls = self.cur["class"]
        best = max((d.results[0].hypothesis.score for d in m.detections
                    if d.results and d.results[0].hypothesis.class_id == cls), default=0.0)
        self.hover_best = max(self.hover_best, best)
        if best >= self.min_conf:
            self.hover_hits += 1

    # ---------------- PX4 output ----------------
    def _us(self):
        return self.get_clock().now().nanoseconds // 1000

    def _command(self, command, p1=0.0, p2=0.0):
        c = VehicleCommand(timestamp=self._us(), command=command, param1=float(p1), param2=float(p2),
                           target_system=self.sysid, target_component=1, source_system=1, source_component=1,
                           from_external=True)
        self.pub_cmd.publish(c)

    def _stream(self, yaw):
        self.pub_mode.publish(OffboardControlMode(timestamp=self._us(), position=True))
        sp = TrajectorySetpoint(timestamp=self._us())
        sp.position = [float(v) for v in self.sp]
        sp.velocity = [NAN, NAN, NAN]; sp.acceleration = [NAN, NAN, NAN]; sp.jerk = [NAN, NAN, NAN]
        sp.yaw, sp.yawspeed = float(yaw), NAN
        self.pub_sp.publish(sp)

    # ---------------- helpers ----------------
    def _ned(self, lat, lon):
        l = self.loc
        return ((lat - l.ref_lat) * M_LAT, (lon - l.ref_lon) * M_LON * math.cos(math.radians(l.ref_lat)))

    def _say(self, state, **kw):
        self.state, self.t_state = state, time.monotonic()
        msg = dict(state=state, **kw)
        self.pub_status.publish(String(data=json.dumps(msg)))
        self.get_logger().info(f"re-fly: {state} {json.dumps(kw) if kw else ''}")

    def _make_plan(self):
        here = (self.loc.x, self.loc.y)
        todo = []
        for a in self.alerts.values():
            n, e = self._ned(a.latitude, a.longitude)
            todo.append(dict(id=a.id, cls=a.class_name, n=n, e=e, conf=round(float(a.max_conf), 2)))
        plan = []
        while todo and len(plan) < self.max_targets:          # nearest first
            nxt = min(todo, key=lambda t: math.hypot(t["n"] - here[0], t["e"] - here[1]))
            todo.remove(nxt)
            yaw = math.atan2(nxt["e"] - here[1], nxt["n"] - here[0])   # approach direction, NED yaw
            plan.append(dict(id=nxt["id"], **{"class": nxt["cls"]}, alert_conf=nxt["conf"], yaw=yaw,
                             n=nxt["n"] - self.standoff * math.cos(yaw), e=nxt["e"] - self.standoff * math.sin(yaw)))
            here = (nxt["n"], nxt["e"])
        return plan

    def _move_carrot(self, target, dt=0.1):
        """Moves the setpoint towards target at the horizontal / vertical speed limits; True when it is there."""
        n, e, d = self.sp
        dn, de, dd = target[0] - n, target[1] - e, target[2] - d
        dh = math.hypot(dn, de)
        sh = min(dh, self.speed * dt)
        if dh > 1e-6:
            n, e = n + dn / dh * sh, e + de / dh * sh
        d += max(-self.vspeed * dt, min(self.vspeed * dt, dd))
        self.sp = [n, e, d]
        return dh <= sh and abs(dd) <= self.vspeed * dt

    # ---------------- state machine (10 Hz) ----------------
    def _tick(self):
        s, l = self.status, self.loc
        if s is None or l is None:
            return
        armed = s.arming_state == VehicleStatus.ARMING_STATE_ARMED
        nav = s.nav_state
        in_ctrl = self.state in ("handover", "transit", "hover")

        if self.state == "returning":
            # keep the offboard stream alive until PX4 is in Return, so losing it never triggers the offboard failsafe
            if nav == VehicleStatus.NAVIGATION_STATE_AUTO_RTL or not armed:
                self._say("finished", verified=sum(r.get("verdict") == "verified" for r in self.results), total=len(self.results))
                return
            self._stream(self.yaw)
            if time.monotonic() - self.t_state > 0.5 and int((time.monotonic() - self.t_state) * 10) % 10 == 0:
                self._command(VehicleCommand.VEHICLE_CMD_NAV_RETURN_TO_LAUNCH)          # resend once a second
            if time.monotonic() - self.t_state > 10:
                self._say("aborted", reason="PX4 did not accept Return; holding position in OFFBOARD stopped")
            return

        if self.state == "idle":
            if armed and nav == VehicleStatus.NAVIGATION_STATE_AUTO_RTL and not self.done_flight and self.alerts \
                    and l.xy_global and l.xy_valid and l.z_valid:
                self.plan = self._make_plan()
                self.sp = [l.x, l.y, l.z]
                self.yaw = l.heading
                self._say("handover", targets=[dict(id=t["id"], cls=t["class"]) for t in self.plan])
            return

        if in_ctrl:
            if not armed:
                self._say("aborted", reason="disarmed"); self.done_flight = True; return
            if self.state != "handover" and nav != VehicleStatus.NAVIGATION_STATE_OFFBOARD:
                self._say("aborted", reason=f"pilot or failsafe took over (nav_state {nav})"); self.done_flight = True
                return
            self._stream(self.yaw)

        if self.state == "handover":
            # PX4 needs the offboard stream for a moment before it accepts the mode switch
            if time.monotonic() - self.t_state > 1.0 and nav != VehicleStatus.NAVIGATION_STATE_OFFBOARD:
                self._command(VehicleCommand.VEHICLE_CMD_DO_SET_MODE, 1, 6)        # custom main mode 6 = OFFBOARD
            if nav == VehicleStatus.NAVIGATION_STATE_OFFBOARD:
                self._next_target()
            elif time.monotonic() - self.t_state > 6.0:
                self._say("aborted", reason="PX4 did not accept OFFBOARD"); self.done_flight = True
            return

        if self.state == "transit":
            t = self.cur
            arrived_sp = self._move_carrot((t["n"], t["e"], -self.alt))
            self.yaw = t["yaw"]
            close = math.hypot(l.x - t["n"], l.y - t["e"]) < self.arrive_m and abs(l.z + self.alt) < 0.7
            slow = math.hypot(l.vx, l.vy) < 0.5
            if arrived_sp and close and slow:
                self.hover_hits, self.hover_frames, self.hover_best = 0, 0, 0.0
                self._say("hover", id=t["id"], cls=t["class"])
            elif time.monotonic() - self.t_state > 90:
                self.results.append(dict(id=t["id"], **{"class": t["class"]}, verdict="not reached"))
                self._next_target()
            return

        if self.state == "hover" and time.monotonic() - self.t_state >= self.hover_s:
            t = self.cur
            ok = self.hover_frames >= self.min_frames and self.hover_hits >= self.verify_ratio * self.hover_frames
            verdict = "verified" if ok else "not seen up close"
            self.results.append(dict(id=t["id"], **{"class": t["class"]}, alert_conf=t["alert_conf"], verdict=verdict,
                                     frames=self.hover_frames, hits=self.hover_hits, best_conf=round(self.hover_best, 2)))
            self.get_logger().info(f"re-fly: alert #{t['id']} {t['class']}: {verdict} "
                                   f"({self.hover_hits}/{self.hover_frames} frames, best {self.hover_best:.2f})")
            self._next_target()

    def _next_target(self):
        if self.plan:
            self.cur = self.plan.pop(0)
            self._say("transit", id=self.cur["id"], cls=self.cur["class"])
        else:
            self.cur = None
            self.sp = [self.loc.x, self.loc.y, self.loc.z]          # hold here until Return takes over
            self._command(VehicleCommand.VEHICLE_CMD_NAV_RETURN_TO_LAUNCH)
            self.done_flight = True
            report = dict(altitude_m=self.alt, standoff_m=round(self.standoff, 1), hover_s=self.hover_s, results=self.results)
            self.pub_report.publish(String(data=json.dumps(report)))
            self._say("returning")


def main():
    rclpy.init(); n = Refly()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
