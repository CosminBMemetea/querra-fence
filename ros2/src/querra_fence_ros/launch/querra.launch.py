"""QUERRA Fence on ROS 2.

Phase 1 (always): cameras from the panel hub, GPS from gpsd, LD2450 radar, static TFs, stats, foxglove_bridge.
Phase 2 (detector:=sim or detector:=usb): YOLO11n v0.3 TensorRT detector + 5-of-8 GPS alert confirmation.
  detector:=sim  replays the recorded Gazebo mission (sim_source:=/sim/m1, or tcp://<mac>:5601 for the live sim)
  detector:=usb  runs on the real USB camera with gpsd as the position source (bench use: no fence, no alerts)
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def tf(child, xyz, rpy):
    return Node(package="tf2_ros", executable="static_transform_publisher", name=f"tf_{child}",
                arguments=["--x", xyz[0], "--y", xyz[1], "--z", xyz[2], "--roll", rpy[0], "--pitch", rpy[1], "--yaw", rpy[2],
                           "--frame-id", "base_link", "--child-frame-id", child])


def generate_launch_description():
    panel, det = LaunchConfiguration("panel"), LaunchConfiguration("detector")
    is_sim = IfCondition(PythonExpression(["'", det, "' == 'sim'"]))
    is_usb = IfCondition(PythonExpression(["'", det, "' == 'usb'"]))
    cams = [Node(package="querra_fence_ros", executable="hub_camera", name=f"{c}_camera", namespace=f"camera/{c}",
                 parameters=[{"camera": c, "url": ["http://", panel, f"/stream/{c}.mjpg"]}], output="screen")
            for c in ("usb", "csi")]
    return LaunchDescription([
        DeclareLaunchArgument("panel", default_value="127.0.0.1:8080", description="QUERRA panel host:port (camera hub)"),
        DeclareLaunchArgument("radar", default_value="http://127.0.0.1:8077/events"),
        DeclareLaunchArgument("foxglove", default_value="true"),
        DeclareLaunchArgument("detector", default_value="none", description="none | sim | usb"),
        DeclareLaunchArgument("sim_source", default_value="/sim/m1", description="recording dir or tcp://host:port"),
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
        # ---- phase 2: simulator camera (recorded or live Gazebo mission) -> detector -> alert confirmation ----
        Node(package="querra_fence_ros", executable="sim_camera", name="sim_camera", namespace="sim", condition=is_sim,
             parameters=[{"source": LaunchConfiguration("sim_source")}], output="screen"),
        Node(package="querra_fence_ros", executable="detector", name="fence_detector", condition=is_sim,
             parameters=[{"image": "/sim/camera/image_raw/compressed"}], output="screen"),
        Node(package="querra_fence_ros", executable="alerts", name="alert_confirm", condition=is_sim,
             parameters=[{"telemetry": "/sim/telemetry"}], output="screen"),
        # ---- phase 2 on the real USB camera (1280x720 frames from the hub are 640x360 live view) ----
        Node(package="querra_fence_ros", executable="detector", name="fence_detector", condition=is_usb,
             parameters=[{"image": "/camera/usb/image_raw/compressed"}], output="screen"),
    ])
