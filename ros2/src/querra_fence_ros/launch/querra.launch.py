"""QUERRA Fence phase 1: cameras (from the panel hub), GPS (gpsd), LD2450 radar (ld2450-radar service), static TFs,
and optionally foxglove_bridge on port 8765 (foxglove:=true)."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def tf(child, xyz, rpy):
    return Node(package="tf2_ros", executable="static_transform_publisher", name=f"tf_{child}",
                arguments=["--x", xyz[0], "--y", xyz[1], "--z", xyz[2], "--roll", rpy[0], "--pitch", rpy[1], "--yaw", rpy[2],
                           "--frame-id", "base_link", "--child-frame-id", child])


def generate_launch_description():
    panel = LaunchConfiguration("panel")
    cams = [Node(package="querra_fence_ros", executable="hub_camera", name=f"{c}_camera", namespace=f"camera/{c}",
                 parameters=[{"camera": c, "url": ["http://", panel, f"/stream/{c}.mjpg"]}], output="screen")
            for c in ("usb", "csi")]
    return LaunchDescription([
        DeclareLaunchArgument("panel", default_value="127.0.0.1:8080", description="QUERRA panel host:port (camera hub)"),
        DeclareLaunchArgument("radar", default_value="http://127.0.0.1:8077/events"),
        DeclareLaunchArgument("foxglove", default_value="true"),
        *cams,
        Node(package="querra_fence_ros", executable="stats", name="querra_stats", output="log"),
        Node(package="querra_fence_ros", executable="gpsd_gps", name="gps", output="screen"),
        Node(package="querra_fence_ros", executable="ld2450", name="ld2450", parameters=[{"url": LaunchConfiguration("radar")}], output="screen"),
        # Mounting offsets are placeholders until the sensors are measured on the airframe.
        tf("usb_camera_optical", ["0.10", "0", "0"], ["-1.5708", "0", "-1.5708"]),
        tf("csi_camera_optical", ["0.10", "0.03", "0"], ["-1.5708", "0", "-1.5708"]),
        tf("radar", ["0.12", "0", "0"], ["0", "0", "0"]),
        tf("gps", ["0", "0", "0.10"], ["0", "0", "0"]),
        Node(package="foxglove_bridge", executable="foxglove_bridge", name="foxglove_bridge", condition=IfCondition(LaunchConfiguration("foxglove")),
             parameters=[{"port": 8765, "address": "0.0.0.0", "send_buffer_limit": 20000000}], output="log"),
    ])
