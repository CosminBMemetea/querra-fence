#!/usr/bin/env bash
# Still images of the pasture world from fixed viewpoints: tools/snap_world.sh [--look rich|classic] [--out run/snaps]
# Stop the main simulation first (./stop.sh). Run from a normal Terminal.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
set +u; source "$PX4_DIR/build/px4_sitl_default/gz_env.sh"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=gardian-snap GZ_IP=127.0.0.1
exec "$CONDA_PREFIX/bin/python" -u "$ROOT/tools/snap_world.py" "$@"
