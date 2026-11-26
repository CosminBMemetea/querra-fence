"""Shared test setup: tools/ and the ROS 2 package on the import path, and stand-ins for ROS 2 where it is not
installed (the Mac, GitHub), so the nodes' logic can be tested without a robot. On the Jetson the real ROS 2 is used.

The stand-ins: message classes take keyword arguments and grow sub-messages on first use (msg.header.stamp.sec);
rclpy.node.Node records what a node publishes and hands out parameter defaults; everything else is a MagicMock.
"""
import importlib.util
import os
import sys
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "ros2", "src", "querra_fence_ros"))

ROS_MODULES = ["rclpy", "rclpy.node", "rclpy.qos", "rclpy.time", "tf2_ros"]
MSG_PACKAGES = ["builtin_interfaces", "geometry_msgs", "rosgraph_msgs", "nav_msgs", "sensor_msgs", "std_msgs",
                "visualization_msgs", "vision_msgs", "querra_fence_msgs"]


class Msg:
    """A ROS message stand-in: Msg(a=1).a == 1, and Msg().header.stamp is a Msg too."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        v = Msg()
        setattr(self, name, v)
        return v


class Pub:
    def __init__(self, topic):
        self.topic, self.msgs = topic, []

    def publish(self, m):
        self.msgs.append(m)


class Node:
    """rclpy.node.Node stand-in: parameters take their defaults; publishers record their messages."""

    def __init__(self, name, *a, **k):
        self.node_name, self.pubs = name, {}

    def declare_parameter(self, name, value):
        return types.SimpleNamespace(value=value)

    def create_publisher(self, typ, topic, qos):
        self.pubs[topic] = Pub(topic)
        return self.pubs[topic]

    def create_subscription(self, *a, **k):
        return None

    def create_timer(self, *a, **k):
        return None

    def get_logger(self):
        return mock.MagicMock()


class _Stub(types.ModuleType):
    def __init__(self, name, factory):
        super().__init__(name)
        self._factory = factory

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        v = self._factory(name)
        setattr(self, name, v)
        return v


def install_ros_stubs():
    if importlib.util.find_spec("rclpy") is not None:
        return False
    for n in ROS_MODULES:
        sys.modules.setdefault(n, _Stub(n, lambda name, n=n: mock.MagicMock(name=n + "." + name)))
    for p in MSG_PACKAGES:
        sys.modules.setdefault(p, _Stub(p, lambda name: mock.MagicMock()))
        sys.modules.setdefault(p + ".msg", _Stub(p + ".msg", lambda name: type(name, (Msg,), {})))
    sys.modules["rclpy.node"].Node = Node
    return True


STUBBED = install_ros_stubs()
