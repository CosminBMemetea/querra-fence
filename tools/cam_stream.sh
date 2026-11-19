#!/usr/bin/env bash
# Streams the drone camera (/fence_cam/image) to the Jetson: tcp://<this-mac>:5601 (JPEG + telemetry).
# Start the simulation first (./start.sh headless or ./start.sh), then: tools/cam_stream.sh [--port 5601]
# On the Jetson: python3 -s jetson-launch.py run --source sim:<mac-ip>:5601 --material synthetic ...
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
set +u; source "$PX4_DIR/build/px4_sitl_default/gz_env.sh"; set -u
export GZ_PARTITION=gardian GZ_IP=127.0.0.1   # same transport settings as start.sh
exec "$CONDA_PREFIX/bin/python" -u "$ROOT/tools/cam_stream.py" "$@"
