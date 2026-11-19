#!/usr/bin/env bash
# QUERRA Fence ROS 2 (Humble in Docker; image, workspace and bags on /ssd). The QUERRA panel has the same controls.
#
#   ./ros.sh start [launch args]   start all nodes in the background, e.g. ./ros.sh start foxglove:=false
#   ./ros.sh demo [tcp://MAC:5601] phase 2 demo: sensors + recorded (or live) Gazebo mission -> TensorRT detector
#                                  -> 5-of-8 alert confirmation, Foxglove on :8765 (layout: foxglove/querra-layout.json)
#   ./ros.sh stop                  stop and remove the container
#   ./ros.sh status                container state, nodes and topic rates (from the stats node)
#   ./ros.sh record [SECONDS]      MCAP bag of all QUERRA topics to /ssd/querra/bags (no SECONDS: until Ctrl-C)
#   ./ros.sh bags                  list recorded bags
#   ./ros.sh doctor                check docker, image, disk, panel hub, gpsd, radar service and ports
#   ./ros.sh logs                  follow the nodes' output
#   ./ros.sh shell                 a sourced shell inside the container (ros2 topic echo /radar/targets ...)
#   ./ros.sh build                 (re)build the querra-ros:humble image
#
# Foxglove Studio: open ws://<jetson>:8765. The nodes never open /dev/video*, the GPS port or /dev/ttyUSB0:
# cameras come from the panel hub (:8080), GPS from gpsd (:2947), radar from the ld2450-radar service (:8077).
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
NAME=querra-ros IMAGE=querra-ros:humble BAGS=/ssd/querra/bags
WS=${QUERRA_ROS_WS:-$HERE}
TOPICS="/camera/usb/image_raw/compressed /camera/csi/image_raw/compressed /gps/fix /gps/info /radar/targets /radar/points /radar/markers /tf_static /sim/camera/image_raw/compressed /sim/telemetry /sim/gps/fix /detections /detections/image /detections/latency_ms /fence/alerts /fence/alerts/fix /fence/alerts/count"
running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ]; }
# Phase 2 detector: JetPack's TensorRT 10 + CUDA 12.6, querra_scout's YOLODetector and the engines, all read-only from
# the host (nothing is copied to the root disk). /sim holds recorded Gazebo missions for the demo.
L=/usr/lib/aarch64-linux-gnu Q=${QUERRA_SCOUT:-/home/mmx/querra-scout-20261107}
TRT=(-v /usr/local/cuda-12.6:/usr/local/cuda-12.6:ro -v /usr/lib/python3.10/dist-packages/tensorrt:/usr/lib/python3/dist-packages/tensorrt:ro
     -v "$Q/querra_scout:/opt/querra_scout/querra_scout:ro" -v "$Q/models/fence-yolo:/models:ro" -v /ssd/querra/sim:/sim:ro
     -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/opt/querra_scout
     -e LD_LIBRARY_PATH=/usr/local/cuda-12.6/targets/aarch64-linux/lib:/usr/lib/aarch64-linux-gnu/nvidia)
for f in libnvinfer.so.10 libnvinfer_plugin.so.10 libnvonnxparser.so.10; do [ -e "$L/$f" ] && TRT+=(-v "$(readlink -f "$L/$f"):$L/$f:ro"); done
ex() { docker exec "$NAME" bash -lc "source /ws/install/setup.bash && $*"; }
need() { running || { echo "ROS 2 is not running: ./ros.sh start"; exit 1; }; }
case "${1:-help}" in
  build) docker build -t "$IMAGE" "$HERE/docker" ;;
  start)
    shift; docker rm -f "$NAME" >/dev/null 2>&1 || true; mkdir -p "$BAGS" "$WS/build" "$WS/install" "$WS/log"
    rm -f "$WS/stats.json"
    docker run -d --name "$NAME" --network host --ipc host --restart no -v "$WS:/ws" -v "$BAGS:/bags" "${TRT[@]}" "$IMAGE" \
      ros2 launch querra_fence_ros querra.launch.py "$@" >/dev/null
    for _ in $(seq 1 120); do [ -f "$WS/stats.json" ] && break; running || break; sleep 1; done
    if running; then echo "ROS 2 running (foxglove: ws://$(hostname).local:8765)"; else echo "start failed:"; docker logs --tail 30 "$NAME"; exit 1; fi ;;
  demo)
    src=${2:-/sim/m1}; "$0" start detector:=sim sim_source:="$src"
    echo "demo: $src -> /sim/camera -> fence_detector (TensorRT) -> alert_confirm -> /fence/alerts"
    echo "Foxglove: open ws://$(hostname -I | cut -d' ' -f1):8765 and import ros2/foxglove/querra-layout.json" ;;
  stop) docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped" || echo "not running"; rm -f "$WS/stats.json" ;;
  status)
    running || { echo "stopped"; exit 0; }
    echo "running since $(docker inspect -f '{{.State.StartedAt}}' "$NAME" | cut -c1-19)Z"
    python3 - "$WS/stats.json" <<'PY'
import json, sys
try: s = json.load(open(sys.argv[1]))
except Exception: print("no stats yet"); sys.exit()
print("nodes:", " ".join(s["nodes"]))
for k, v in s["topics"].items(): print(f"  {v['hz']:6.1f} Hz  {k}  ({v['type']})")
PY
    ;;
  record)
    need; secs=${2:-0}; out="/bags/querra-$(date +%Y%m%d-%H%M%S)"
    if [ "$secs" -gt 0 ]; then ex "timeout -s INT $secs ros2 bag record -s mcap -o $out $TOPICS" >/dev/null 2>&1 || true
    else docker exec -it "$NAME" bash -lc "source /ws/install/setup.bash && ros2 bag record -s mcap -o $out $TOPICS"; fi
    echo "bag: $BAGS/$(basename "$out") ($(du -sh "$BAGS/$(basename "$out")" | cut -f1))" ;;
  bags) ls -1t "$BAGS" 2>/dev/null | while read -r b; do printf '%-28s %6s\n' "$b" "$(du -sh "$BAGS/$b" | cut -f1)"; done ;;
  logs) docker logs -f --tail 50 "$NAME" ;;
  shell) need; docker exec -it "$NAME" bash -lc "source /ws/install/setup.bash && exec bash" ;;
  doctor)
    ok() { printf '  \033[32mok\033[0m   %s\n' "$1"; }; bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
    port() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
    command -v docker >/dev/null && ok "docker $(docker --version | cut -d' ' -f3 | tr -d ,)" || bad "docker missing"
    dr=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo "?")
    [[ $dr == /ssd/* ]] && ok "docker data-root $dr (on the SSD)" || bad "docker data-root $dr is not on /ssd"
    docker image inspect "$IMAGE" >/dev/null 2>&1 && ok "image $IMAGE" || bad "image $IMAGE missing: ./ros.sh build"
    running && ok "container $NAME running" || echo "  --   container $NAME stopped (./ros.sh start)"
    port 8080 && ok "panel hub :8080 (cameras)" || bad "panel not reachable on :8080: cameras will be silent"
    port 2947 && ok "gpsd :2947" || bad "gpsd not reachable on :2947"
    curl -sf -m2 http://127.0.0.1:8077/health >/dev/null && ok "ld2450-radar service :8077" || bad "ld2450-radar service offline (sudo systemctl status ld2450-radar)"
    running && { port 8765 && ok "foxglove_bridge :8765" || bad "foxglove_bridge not listening"; }
    s=$(df -BG --output=avail /ssd | tail -1 | tr -dc 0-9); [ "$s" -gt 20 ] && ok "/ssd free ${s} GB" || bad "/ssd free ${s} GB"
    r=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ "$r" -gt 2 ] && ok "root disk free ${r} GB (ROS uses none)" || bad "root disk free ${r} GB"
    echo "  bags: $(ls "$BAGS" 2>/dev/null | wc -l) in $BAGS ($(du -sh "$BAGS" 2>/dev/null | cut -f1))" ;;
  help|-h|--help|*) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
