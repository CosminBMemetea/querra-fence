"""QUERRA Fence on ROS 2.

Phase 1 (always): cameras from the panel hub, GPS from gpsd, LD2450 radar, static TFs, stats, foxglove_bridge.
Phase 2 (detector:=sim or detector:=usb): YOLO11n v0.3 TensorRT detector + 5-of-8 GPS alert confirmation.
  detector:=sim  replays the recorded Gazebo mission (sim_source:=/sim/m1, or tcp://<mac>:5601 for the live sim)
  detector:=usb  runs on the real USB camera with gpsd as the position source (bench use: no fence, no alerts)
Phase 3 (px4:=true): the micro-ROS agent on UDP 8888 bridges PX4's uXRCE-DDS client into ROS 2 (/fmu/out/*), and
  px4_pose turns the vehicle's own position and heading into /px4/telemetry, which alert_confirm then uses
  instead of the simulator's telemetry.
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
    px4 = LaunchConfiguration("px4")
    is_px4 = IfCondition(px4)
    telemetry = PythonExpression(["'/px4/telemetry' if '", px4, "'.lower() in ('true', '1') else '/sim/telemetry'"])
    is_refly = IfCondition(PythonExpression(["'", px4, "'.lower() in ('true', '1') and '", LaunchConfiguration("refly"),
                                             "'.lower() in ('true', '1')"]))
    cams = [Node(package="querra_fence_ros", executable="hub_camera", name=f"{c}_camera", namespace=f"camera/{c}",
                 parameters=[{"camera": c, "url": ["http://", panel, f"/stream/{c}.mjpg"]}], output="screen")
            for c in ("usb", "csi")]
    return LaunchDescription([
        DeclareLaunchArgument("panel", default_value="127.0.0.1:8080", description="QUERRA panel host:port (camera hub)"),
        DeclareLaunchArgument("radar", default_value="http://127.0.0.1:8077/events"),
        DeclareLaunchArgument("foxglove", default_value="true"),
        DeclareLaunchArgument("detector", default_value="none", description="none | sim | usb"),
        DeclareLaunchArgument("sim_source", default_value="/sim/m1", description="recording dir or tcp://host:port"),
        DeclareLaunchArgument("px4", default_value="false", description="true: PX4 over uXRCE-DDS (agent on UDP px4_port)"),
        DeclareLaunchArgument("px4_port", default_value="8888"),
        DeclareLaunchArgument("refly", default_value="false",
                              description="true (with px4:=true): after the mission, re-fly every confirmed fault low (OFFBOARD)"),
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
             parameters=[{"telemetry": telemetry}], output="screen"),
        # ---- phase 3: PX4 over uXRCE-DDS (SITL on the Mac through tools/uxrce_relay.py, or the flight controller) ----
        Node(package="micro_ros_agent", executable="micro_ros_agent", name="xrce_agent", condition=is_px4,
             arguments=["udp4", "-p", LaunchConfiguration("px4_port")], output="log"),
        Node(package="querra_fence_ros", executable="px4_pose", name="px4_pose", condition=is_px4, output="screen"),
        Node(package="querra_fence_ros", executable="refly", name="fence_refly", condition=is_refly, output="screen"),
        # ---- phase 2 on the real USB camera (1280x720 frames from the hub are 640x360 live view) ----
        Node(package="querra_fence_ros", executable="detector", name="fence_detector", condition=is_usb,
             parameters=[{"image": "/camera/usb/image_raw/compressed"}], output="screen"),
    ])
