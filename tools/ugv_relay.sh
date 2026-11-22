#!/usr/bin/env bash
# Serves the ground robot (forest world) to the Jetson: tcp://<this-mac>:5611. Started by ./ugv.sh; on its own, start
# the simulation first. On the Jetson: ./ros.sh ugv tcp://<mac-ip>:5611
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
set +u; source "$PX4_DIR/build/px4_sitl_default/gz_env.sh"; set -u
export GZ_PARTITION=querra_ugv GZ_IP=127.0.0.1   # same transport settings as ugv.sh
exec "$CONDA_PREFIX/bin/python" -u "$ROOT/tools/ugv_relay.py" "$@"
