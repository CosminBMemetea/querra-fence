#!/usr/bin/env bash
# QUERRA Fence ROS 2 (Humble in Docker; image, workspace and bags on /ssd). The QUERRA panel has the same controls.
#
#   ./ros.sh start [launch args]   start all nodes in the background, e.g. ./ros.sh start foxglove:=false
#   ./ros.sh demo [tcp://MAC:5601] phase 2 demo: sensors + recorded (or live) Gazebo mission -> TensorRT detector
#                                  -> 5-of-8 alert confirmation, Foxglove on :8765 (layout: foxglove/querra-layout.json)
#   ./ros.sh demo tcp://MAC:5601 px4:=true
#                                  phase 3: live simulation, alerts placed with PX4's own pose over uXRCE-DDS
#                                  (on the Mac: ./start.sh headless, tools/cam_stream.sh, tools/uxrce_relay.py JETSON)
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
TOPICS="/camera/usb/image_raw/compressed /camera/csi/image_raw/compressed /gps/fix /gps/info /radar/targets /radar/points /radar/markers /tf_static /sim/camera/image_raw/compressed /sim/telemetry /sim/gps/fix /detections /detections/image /detections/latency_ms /fence/alerts /fence/alerts/updates /fence/alerts/fix /fence/alerts/count /px4/telemetry /px4/gps/fix /fmu/out/vehicle_global_position /fmu/out/vehicle_local_position_v1 /fmu/out/vehicle_attitude /fmu/out/vehicle_status_v5 /fence/refly/status /fence/refly/report"
running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ]; }
# LAN address for Foxglove: the source address of the default route (hostname -I can list docker0 or l4tbr0 first).
lan_ip() { ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}' | grep . || echo "$(hostname).local"; }
# Phase 2 detector: JetPack's TensorRT 10 + CUDA 12.6, querra_scout's YOLODetector and the engines, all read-only from
# the host (nothing is copied to the root disk). /sim holds recorded Gazebo missions for the demo.
# Host folders are mounted only when they exist: docker -v would otherwise create them empty and root-owned.
L=/usr/lib/aarch64-linux-gnu Q=${QUERRA_SCOUT:-/home/mmx/querra-scout-20261107} SIM=/ssd/querra/sim
TRT=(-e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/opt/querra_scout
     -e LD_LIBRARY_PATH=/usr/local/cuda-12.6/targets/aarch64-linux/lib:/usr/lib/aarch64-linux-gnu/nvidia)
mnt() { if [ -e "$1" ]; then TRT+=(-v "$1:$2:ro"); else MISSING+=("$1"); fi; }
MISSING=()
mnt /usr/local/cuda-12.6 /usr/local/cuda-12.6
mnt /usr/lib/python3.10/dist-packages/tensorrt /usr/lib/python3/dist-packages/tensorrt
mnt "$Q/querra_scout" /opt/querra_scout/querra_scout
mnt "$Q/models/fence-yolo" /models
mnt "$SIM" /sim
for f in libnvinfer.so.10 libnvinfer_plugin.so.10 libnvonnxparser.so.10; do [ -e "$L/$f" ] && TRT+=(-v "$(readlink -f "$L/$f"):$L/$f:ro"); done
# GPU access: ask for the NVIDIA runtime explicitly instead of relying on the daemon's default-runtime.
nvidia_rt() { docker info -f '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; }
RT=(); nvidia_rt && RT=(--runtime nvidia)
ex() { docker exec "$NAME" bash -lc "source /ws/install/setup.bash && $*"; }
need() { running || { echo "ROS 2 is not running: ./ros.sh start"; exit 1; }; }
case "${1:-help}" in
  build) docker build -t "$IMAGE" "$HERE/docker" ;;
  start)
    shift; docker rm -f "$NAME" >/dev/null 2>&1 || true; mkdir -p "$BAGS" "$WS/build" "$WS/install" "$WS/log"
    rm -f "$WS/stats.json"
    [ ${#MISSING[@]} -gt 0 ] && echo "note: not mounted (missing on the host): ${MISSING[*]}"
    nvidia_rt || echo "note: docker has no 'nvidia' runtime: the detector may not reach the GPU (./ros.sh doctor)"
    docker run -d --name "$NAME" "${RT[@]}" --network host --ipc host --restart no -v "$WS:/ws" -v "$BAGS:/bags" "${TRT[@]}" "$IMAGE" \
      ros2 launch querra_fence_ros querra.launch.py "$@" >/dev/null
    for _ in $(seq 1 120); do [ -f "$WS/stats.json" ] && break; running || break; sleep 1; done
    if running; then echo "ROS 2 running (foxglove: ws://$(lan_ip):8765)"; else echo "start failed:"; docker logs --tail 30 "$NAME"; exit 1; fi ;;
  demo)
    src=${2:-/sim/m1}
    case "$src" in
      tcp://*) ;;
      /sim/*) [ -s "$SIM/${src#/sim/}/frames.jsonl" ] || { echo "no recording at $SIM/${src#/sim/} (frames.jsonl missing or empty)"; exit 1; } ;;
    esac
    "$0" start detector:=sim sim_source:="$src" "${@:3}"
    case " ${*:3} " in *" px4:=true "*) echo "phase 3: micro-ROS agent on UDP 8888, alerts use /px4/telemetry (PX4's own pose)";; esac
    echo "demo: $src -> /sim/camera -> fence_detector (TensorRT) -> alert_confirm -> /fence/alerts"
    echo "Foxglove: open ws://$(lan_ip):8765 and import ros2/foxglove/querra-layout.json" ;;
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
    nvidia_rt && ok "docker nvidia runtime" || bad "docker has no 'nvidia' runtime (nvidia-container-toolkit): no GPU for the detector"
    running && ok "container $NAME running" || echo "  --   container $NAME stopped (./ros.sh start)"
    [ -d "$Q/querra_scout" ] && ok "querra_scout $Q/querra_scout" || bad "querra_scout not found in $Q (set QUERRA_SCOUT)"
    eng=$Q/models/fence-yolo/fence-yolo11n-v0.3-fp16.engine   # the detector node's default 'engine' parameter
    [ -s "$eng" ] && ok "TensorRT engine $(basename "$eng")" || bad "$eng missing: the detector cannot start"
    [ -s "$SIM/m1/frames.jsonl" ] && ok "demo recording $SIM/m1 ($(wc -l < "$SIM/m1/frames.jsonl") frames)" || bad "demo recording $SIM/m1 missing: ./ros.sh demo will not run"
    port 8080 && ok "panel hub :8080 (cameras)" || bad "panel not reachable on :8080: cameras will be silent"
    port 2947 && ok "gpsd :2947" || bad "gpsd not reachable on :2947"
    curl -sf -m2 http://127.0.0.1:8077/health >/dev/null && ok "ld2450-radar service :8077" || bad "ld2450-radar service offline (sudo systemctl status ld2450-radar)"
    running && { port 8765 && ok "foxglove_bridge :8765" || bad "foxglove_bridge not listening"; }
    docker run --rm --entrypoint test "$IMAGE" -x /opt/uros/install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent 2>/dev/null \
      && ok "micro-ROS agent in the image (phase 3)" || bad "no micro-ROS agent in $IMAGE: ./ros.sh build"
    if running && docker exec "$NAME" pgrep -f micro_ros_agent >/dev/null 2>&1; then
      ss -lun 2>/dev/null | grep -q ':8888 ' && ok "uXRCE-DDS agent listening on UDP 8888" || bad "micro-ROS agent runs but UDP 8888 is not open"
    fi
    # '|| true': under set -e/pipefail a failing df would otherwise end doctor before the remaining checks
    if mountpoint -q /ssd; then
      s=$(df -BG --output=avail /ssd 2>/dev/null | tail -1 | tr -dc 0-9) || true
      [ "${s:-0}" -gt 20 ] && ok "/ssd free ${s} GB" || bad "/ssd free ${s:-?} GB"
    else bad "/ssd is not mounted: bags and the docker data-root live there"; fi
    r=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc 0-9) || true
    [ "${r:-0}" -gt 2 ] && ok "root disk free ${r} GB (ROS uses none)" || bad "root disk free ${r:-?} GB"
    echo "  bags: $(ls "$BAGS" 2>/dev/null | wc -l) in $BAGS ($(du -sh "$BAGS" 2>/dev/null | cut -f1))" ;;
  help|-h|--help|*) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
