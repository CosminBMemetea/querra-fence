#!/usr/bin/env bash
# QUERRA Fence ROS 2 on the Jetson (Docker, ROS 2 Humble; image and data on /ssd).
#   ./ros.sh build            build the querra-ros:humble image
#   ./ros.sh start [args]     start the nodes in the background (args go to the launch file, e.g. foxglove:=false)
#   ./ros.sh stop             stop and remove the container
#   ./ros.sh status           container state + topic list
#   ./ros.sh record [secs]    rosbag2 MCAP of all QUERRA topics to /ssd/querra/bags (Ctrl-C or secs to stop)
#   ./ros.sh shell            a sourced shell in the running container (ros2 topic hz ...)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
NAME=querra-ros IMAGE=querra-ros:humble BAGS=/ssd/querra/bags
WS=${QUERRA_ROS_WS:-$HERE}                      # contains src/
TOPICS="/camera/usb/image_raw/compressed /camera/csi/image_raw/compressed /gps/fix /gps/info /radar/targets /radar/points /radar/markers /tf_static"
ex() { docker exec "$NAME" bash -lc "source /ws/install/setup.bash && $*"; }
case "${1:-}" in
  build) docker build -t "$IMAGE" "$HERE/docker" ;;
  start)
    shift; docker rm -f "$NAME" >/dev/null 2>&1 || true; mkdir -p "$BAGS" "$WS/build" "$WS/install" "$WS/log"
    docker run -d --name "$NAME" --network host --ipc host --restart no -v "$WS:/ws" -v "$BAGS:/bags" "$IMAGE" \
      ros2 launch querra_fence_ros querra.launch.py "$@" >/dev/null
    for _ in $(seq 1 90); do docker logs "$NAME" 2>&1 | grep -q "reading http" && break; sleep 1; done
    docker ps --filter name="$NAME" --format '{{.Names}} {{.Status}}'; docker logs --tail 8 "$NAME" ;;
  stop) docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped" || echo "not running" ;;
  status) docker ps -a --filter name="$NAME" --format '{{.Names}} {{.Status}}'; ex "ros2 topic list" 2>/dev/null || true ;;
  record)
    secs=${2:-0}; out="/bags/querra-$(date +%Y%m%d-%H%M%S)"
    if [ "$secs" -gt 0 ]; then
      ex "timeout -s INT $secs ros2 bag record -s mcap -o $out $TOPICS" || true
    else
      docker exec -it "$NAME" bash -lc "source /ws/install/setup.bash && ros2 bag record -s mcap -o $out $TOPICS"
    fi
    echo "bag: $BAGS/$(basename "$out")" ;;
  shell) docker exec -it "$NAME" bash -lc "source /ws/install/setup.bash && exec bash" ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
