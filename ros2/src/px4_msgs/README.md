# px4_msgs (minimal)

These are the PX4 messages that QUERRA Fence reads or sends over uXRCE-DDS. They were copied unchanged from
[PX4-Autopilot](https://github.com/PX4/PX4-Autopilot) `msg/` and `msg/versioned/` at commit `53afcc82b2`
(v1.18.0-beta1, 2026-11-13). PX4 is BSD-3-Clause licensed.

The definitions must match the firmware the drone runs. After a PX4 upgrade, copy these files again from the same PX4
tree. A versioned message keeps its version in the topic name:

| Topic | Message |
|---|---|
| `/fmu/out/vehicle_global_position` | `VehicleGlobalPosition` (v0) |
| `/fmu/out/vehicle_local_position_v1` | `VehicleLocalPosition` (v1) |
| `/fmu/out/vehicle_attitude` | `VehicleAttitude` (v0) |
| `/fmu/out/vehicle_status_v5` | `VehicleStatus` (v5) |
| `/fmu/in/offboard_control_mode` | `OffboardControlMode` (not versioned; for re-flying a confirmed fault) |
| `/fmu/in/trajectory_setpoint` | `TrajectorySetpoint` (v0) |
| `/fmu/in/vehicle_command_v1` | `VehicleCommand` (v1) |
| `/fmu/out/vehicle_command_ack_v2` | `VehicleCommandAck` (v2) |

The full upstream package is [PX4/px4_msgs](https://github.com/PX4/px4_msgs). It has about 250 messages, which take far
longer to build on the Jetson.
