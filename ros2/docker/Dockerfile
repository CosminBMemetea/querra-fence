# QUERRA Fence ROS 2 (Humble, arm64). Image and data live on the Jetson SSD (docker data-root /ssd/docker).
FROM ros:humble-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-rosbag2-storage-mcap ros-humble-foxglove-bridge ros-humble-sensor-msgs-py \
      ros-humble-tf2-ros ros-humble-visualization-msgs python3-opencv python3-numpy python3-pil ros-humble-vision-msgs \
    && rm -rf /var/lib/apt/lists/*
ENV ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "querra_fence_ros", "querra.launch.py"]
