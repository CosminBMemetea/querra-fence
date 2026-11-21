#!/usr/bin/env bash
# Auto-labelled YOLO dataset from random Gazebo pastures. Stop the main simulation first (./stop.sh).
# tools/make_dataset.sh [--layouts 10 --frames 350 --out ~/querra-data/fence_yolo]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
set +u; source "$PX4_DIR/build/px4_sitl_default/gz_env.sh"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=gardian-dataset GZ_IP=127.0.0.1
# --run SCRIPT ARGS: another tool that renders with the dataset camera (tools/calibrate_flight_pose.py)
if [ "${1:-}" = "--run" ]; then shift; exec "$CONDA_PREFIX/bin/python" -u "$@"; fi
exec "$CONDA_PREFIX/bin/python" -u "$ROOT/tools/make_dataset.py" "$@"
