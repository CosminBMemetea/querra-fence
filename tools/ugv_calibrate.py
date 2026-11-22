"""Calibrates the ground robot's skid steer in simulation: how far it really turns and drives for a commanded motion.

A skid steer slips sideways when it turns, so it turns less than its wheel speeds say. Real robots fix that with an
"effective track" (wheel_separation x a multiplier) found by driving and measuring; this does the same against
Gazebo's ground truth:

  1. straight at 0.8 m/s for 4 s         -> distance: truth vs wheel odometry
  2. turn in place at 0.6 rad/s for 5 s  -> yaw: truth vs wheel odometry -> effective track
  3. an arc, 0.8 m/s and 0.25 rad/s      -> both

Prints the effective track to put in sim/gen_forest.py ROBOT["effective_track_m"]. Run on a simulation that is
already running (./ugv.sh), with nothing else driving the robot: tools/ugv_calibrate.sh
"""
import math
import threading
import time

from gz.transport13 import Node
from gz.msgs10.odometry_pb2 import Odometry
from gz.msgs10.twist_pb2 import Twist

state = {}
lock = threading.Lock()


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def cb(name):
    def f(msg):
        p, q = msg.pose.position, msg.pose.orientation
        with lock:
            prev = state.get(name)
            yaw = yaw_of(q)
            unwrapped = yaw if prev is None else prev[3] + math.atan2(math.sin(yaw - prev[2]), math.cos(yaw - prev[2]))
            state[name] = (p.x, p.y, yaw, unwrapped)
    return f


def snap():
    with lock:
        return dict(state)


def drive(pub, v, w, secs):
    t = Twist()
    t.linear.x, t.angular.z = v, w
    end = time.time() + secs
    while time.time() < end:
        pub.publish(t)
        time.sleep(0.05)
    t.linear.x = t.angular.z = 0.0
    for _ in range(30):                 # stop and settle
        pub.publish(t)
        time.sleep(0.05)


def delta(a, b, name):
    (x0, y0, _, u0), (x1, y1, _, u1) = a[name], b[name]
    return math.hypot(x1 - x0, y1 - y0), u1 - u0


def main():
    node = Node()
    node.subscribe(Odometry, "/ugv/odom", cb("odom"))
    node.subscribe(Odometry, "/ugv/ground_truth", cb("truth"))
    pub = node.advertise("/ugv/cmd_vel", Twist)
    time.sleep(1.5)
    if "odom" not in snap() or "truth" not in snap():
        raise SystemExit("no /ugv/odom or /ugv/ground_truth: is ./ugv.sh running?")
    results = []
    for label, v, w, secs in (("straight", 0.8, 0.0, 4.0), ("turn in place", 0.0, 0.6, 5.0), ("turn back", 0.0, -0.6, 5.0),
                              ("arc", 0.8, 0.25, 6.0)):
        a = snap()
        drive(pub, v, w, secs)
        b = snap()
        d_t, y_t = delta(a, b, "truth")
        d_o, y_o = delta(a, b, "odom")
        results.append((label, d_t, d_o, y_t, y_o))
        print("%-14s distance truth %5.2f m, odom %5.2f m | yaw truth %7.1f deg, odom %7.1f deg" % (
            label, d_t, d_o, math.degrees(y_t), math.degrees(y_o)))
    turns = [(y_o, y_t) for label, _, _, y_t, y_o in results if label.startswith("turn") and abs(y_t) > 0.05]
    if turns:
        ratio = sum(abs(o) for o, _ in turns) / sum(abs(t) for _, t in turns)
        print("odom over-reports turns x%.2f -> effective track = current track x %.2f" % (ratio, ratio))


if __name__ == "__main__":
    main()
