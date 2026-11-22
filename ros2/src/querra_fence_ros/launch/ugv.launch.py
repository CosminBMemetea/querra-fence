"""QUERRA ground robot (UGV) on ROS 2: the Gazebo forest robot on the Mac, the patrol brain on the Jetson.

  source:=tcp://<mac>:5611    tools/ugv_relay.py on the Mac (./ugv.sh starts it with the forest world)
  pose:=odom                   what the patrol drives on: odom (wheel odometry from the spawn pose, the default),
                               slam (the SLAM pose, needs slam:=mapping or slam:=localization), truth (the
                               simulator's ground truth: only to test the rest of the chain)
  slam:=off                    off | mapping (teach: build a map while patrolling, with loop closure; the map and the
                               route as the map sees it are saved to map:= when the patrol is done) | localization
                               (repeat: localise against the saved map; with pose:=slam the patrol follows the saved
                               route, map:=<...>.route.json)
  map:=/ws/maps/forest         slam_toolbox's serialized map (/ws is /ssd/querra/ros2 on the Jetson)
  patrol:=true                 drive the taught route around the enclosure as soon as it arrives
  speed:=0.8                   patrol speed, m/s

ugv_bridge turns the relay's stream into /ugv/* topics (LiDAR point cloud, IMU, odometry, GNSS, camera, route,
fence, faults, ground truth for scoring) stamped with Gazebo's simulation time, and publishes /clock;
pointcloud_to_laserscan makes /ugv/scan, a 2D slice 0.33-1.7 m above the
ground; slam_toolbox maps or localises on it; ugv_patrol follows the route. Foxglove on :8765.
"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory("querra_fence_ros"), "config")
    slam, pose = LaunchConfiguration("slam"), LaunchConfiguration("pose")
    pose_topic = PythonExpression(["{'truth': '/ugv/ground_truth', 'slam': '/ugv/slam_pose'}.get('", pose, "', '/ugv/odom_map')"])
    slam_on = PythonExpression(["'", slam, "' in ('mapping', 'localization')"])
    save_map = PythonExpression(["'", LaunchConfiguration("map"), "' if '", slam, "' == 'mapping' else ''"])
    save_route = PythonExpression(["'", LaunchConfiguration("map"), ".route.json' if '", slam, "' == 'mapping' else ''"])
    route_file = PythonExpression(["'", LaunchConfiguration("map"), ".route.json' if '", slam, "' == 'localization' and '",
                                   pose, "' == 'slam' else ''"])
    return LaunchDescription([
        DeclareLaunchArgument("source", default_value="tcp://127.0.0.1:5611", description="tools/ugv_relay.py on the Mac"),
        DeclareLaunchArgument("pose", default_value="odom", description="odom | slam | truth"),
        DeclareLaunchArgument("slam", default_value="off", description="off | mapping | localization"),
        DeclareLaunchArgument("map", default_value="/ws/maps/forest", description="slam_toolbox serialized map (no extension)"),
        DeclareLaunchArgument("patrol", default_value="true"),
        DeclareLaunchArgument("speed", default_value="0.8"),
        DeclareLaunchArgument("foxglove", default_value="true"),
        Node(package="querra_fence_ros", executable="stats", name="querra_stats", output="log"),
        Node(package="querra_fence_ros", executable="ugv_bridge", name="ugv_bridge",
             parameters=[{"source": LaunchConfiguration("source"), "slam": slam_on}], output="screen"),
        Node(package="pointcloud_to_laserscan", executable="pointcloud_to_laserscan_node", name="ugv_scan",
             remappings=[("cloud_in", "/ugv/lidar/points"), ("scan", "/ugv/scan")],
             parameters=[{"target_frame": "ugv_base_link", "transform_tolerance": 0.05,
                          "min_height": 0.05, "max_height": 1.4,          # base_link is 0.28 m up: 0.33-1.68 m above ground
                          "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.00698, "scan_time": 0.1,
                          "range_min": 0.45, "range_max": 30.0, "use_inf": True, "inf_epsilon": 1.0,
                          "use_sim_time": True}], output="log"),
        Node(package="slam_toolbox", executable="async_slam_toolbox_node", name="slam_toolbox",
             condition=IfCondition(PythonExpression(["'", slam, "' == 'mapping'"])),
             parameters=[os.path.join(cfg, "ugv_slam_mapping.yaml"), {"use_sim_time": True}], output="screen"),
        Node(package="slam_toolbox", executable="localization_slam_toolbox_node", name="slam_toolbox",
             condition=IfCondition(PythonExpression(["'", slam, "' == 'localization'"])),
             parameters=[os.path.join(cfg, "ugv_slam_localization.yaml"), {"map_file_name": LaunchConfiguration("map"),
                                                                              "use_sim_time": True}],
             output="screen"),
        Node(package="querra_fence_ros", executable="ugv_patrol", name="ugv_patrol", condition=IfCondition(LaunchConfiguration("patrol")),
             parameters=[{"pose_topic": pose_topic, "speed": LaunchConfiguration("speed"), "save_map": save_map,
                          "save_route": save_route, "route_file": route_file}], output="screen"),
        Node(package="foxglove_bridge", executable="foxglove_bridge", name="foxglove_bridge", condition=IfCondition(LaunchConfiguration("foxglove")),
             parameters=[{"port": 8765, "address": "0.0.0.0", "send_buffer_limit": 20000000}], output="log"),
    ])
