cmake_minimum_required(VERSION 3.8)
project(px4_msgs)
# A minimal px4_msgs: only the messages QUERRA Fence uses, copied unchanged from PX4-Autopilot msg/ (see README.md).
# The names and fields must match the PX4 firmware exactly, or the uXRCE-DDS topics will not match.
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/VehicleGlobalPosition.msg" "msg/VehicleLocalPosition.msg" "msg/VehicleAttitude.msg" "msg/VehicleStatus.msg"
  "msg/TrajectorySetpoint.msg" "msg/OffboardControlMode.msg" "msg/VehicleCommand.msg" "msg/VehicleCommandAck.msg")
ament_export_dependencies(rosidl_default_runtime)
ament_package()
