"""QUERRA ground robot (UGV) on ROS 2: the Gazebo forest robot on the Mac, the patrol brain on the Jetson.

  source:=tcp://<mac>:5611    tools/ugv_relay.py on the Mac (./ugv.sh starts it with the forest world)
  pose:=odom                   what the patrol drives on: odom (wheel odometry from the spawn pose, the default),
                               truth (the simulator's ground truth: only to test the rest of the chain)
  patrol:=true                 drive the taught route around the enclosure as soon as it arrives
  speed:=0.8                   patrol speed, m/s

ugv_bridge turns the relay's stream into /ugv/* topics (LiDAR point cloud, IMU, odometry, GNSS, camera, route,
fence, faults, ground truth for scoring); ugv_patrol follows the route. Foxglove on :8765, as in querra.launch.py.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    pose_topic = PythonExpression(["'/ugv/ground_truth' if '", LaunchConfiguration("pose"), "' == 'truth' else '/ugv/odom_map'"])
    return LaunchDescription([
        DeclareLaunchArgument("source", default_value="tcp://127.0.0.1:5611", description="tools/ugv_relay.py on the Mac"),
        DeclareLaunchArgument("pose", default_value="odom", description="odom | truth"),
        DeclareLaunchArgument("patrol", default_value="true"),
        DeclareLaunchArgument("speed", default_value="0.8"),
        DeclareLaunchArgument("foxglove", default_value="true"),
        Node(package="querra_fence_ros", executable="stats", name="querra_stats", output="log"),
        Node(package="querra_fence_ros", executable="ugv_bridge", name="ugv_bridge",
             parameters=[{"source": LaunchConfiguration("source")}], output="screen"),
        Node(package="querra_fence_ros", executable="ugv_patrol", name="ugv_patrol", condition=IfCondition(LaunchConfiguration("patrol")),
             parameters=[{"pose_topic": pose_topic, "speed": LaunchConfiguration("speed")}], output="screen"),
        Node(package="foxglove_bridge", executable="foxglove_bridge", name="foxglove_bridge", condition=IfCondition(LaunchConfiguration("foxglove")),
             parameters=[{"port": 8765, "address": "0.0.0.0", "send_buffer_limit": 20000000}], output="log"),
    ])
