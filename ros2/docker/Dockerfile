# QUERRA Fence ROS 2 (Humble, arm64). Image and data live on the Jetson SSD (docker data-root /ssd/docker).
FROM ros:humble-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-rosbag2-storage-mcap ros-humble-foxglove-bridge ros-humble-sensor-msgs-py \
      ros-humble-tf2-ros ros-humble-visualization-msgs python3-opencv python3-numpy python3-pil ros-humble-vision-msgs \
    && rm -rf /var/lib/apt/lists/*
# Phase 3: micro-ROS agent, the Micro-XRCE-DDS agent built against Humble's own Fast DDS, so PX4's uXRCE-DDS
# client reaches ROS 2 with no second DDS version in the container. There is no arm64 apt package; build from source.
RUN apt-get update && apt-get install -y --no-install-recommends ros-humble-micro-ros-msgs git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/uros/src && git clone --depth 1 -b humble https://github.com/micro-ROS/micro-ROS-Agent.git /opt/uros/src/micro-ROS-Agent \
    && . /opt/ros/humble/setup.sh && cd /opt/uros \
    && colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release --event-handlers console_cohesion- \
    && rm -rf /opt/uros/build /opt/uros/log /opt/uros/src
# Ground robot (UGV): a 2D scan from the 3D LiDAR, SLAM (mapping with loop closure, then localisation against the
# saved map) and the EKF for fusing odometry, IMU and GNSS. KISS-ICP has no Humble arm64 package; slam_toolbox does.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-pointcloud-to-laserscan ros-humble-slam-toolbox ros-humble-robot-localization ros-humble-nav2-map-server \
    && rm -rf /var/lib/apt/lists/*
ENV ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "querra_fence_ros", "querra.launch.py"]
