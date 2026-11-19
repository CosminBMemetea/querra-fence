# QUERRA Fence on ROS 2 (Humble)

Phase 1 of [docs/ros2.md](../docs/ros2.md): the Jetson's sensors as ROS 2 topics, in Docker, with everything on the SSD.

```bash
# on the Jetson, in /ssd/querra/ros2 (a copy of this folder)
./ros.sh build            # once: querra-ros:humble image (ros:humble-ros-base + MCAP + foxglove_bridge)
./ros.sh start            # nodes + foxglove_bridge on ws://<jetson>:8765 (foxglove:=false to skip it)
./ros.sh record 20        # MCAP bag of all QUERRA topics to /ssd/querra/bags (no number: until Ctrl-C)
./ros.sh status           # container state and topic list
./ros.sh shell            # sourced shell inside: ros2 topic hz /radar/targets ...
./ros.sh stop
```

| Package | What |
| --- | --- |
| `querra_fence_msgs` | `RadarTarget`, `RadarTargets`, `GpsInfo` |
| `querra_fence_ros` | `hub_camera`, `gpsd_gps`, `ld2450` nodes and `querra.launch.py` |

The container uses host networking, so the nodes reach the panel hub (`:8080`), gpsd (`:2947`) and the
ld2450-radar service (`:8077`) on localhost. They never open `/dev/video*`, the GPS port or `/dev/ttyUSB0`.
The workspace is mounted at `/ws` and built by the entrypoint when sources change.
