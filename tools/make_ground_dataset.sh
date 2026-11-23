#!/usr/bin/env bash
# Auto-labelled YOLO dataset for the ground robot's side camera, from random Gazebo forests (see the .py for options).
# Stop the forest simulation first (./ugv.sh stop). Output: --out (default ~/querra-data/ground_yolo).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
set +u; source "$PX4_DIR/build/px4_sitl_default/gz_env.sh"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=querra-ground-dataset GZ_IP=127.0.0.1
exec "$CONDA_PREFIX/bin/python" -u "$ROOT/tools/make_ground_dataset.py" "$@"
