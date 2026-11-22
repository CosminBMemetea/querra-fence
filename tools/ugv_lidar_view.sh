#!/usr/bin/env bash
# Pictures of what the ground robot's LiDAR sees, from the running forest simulation (./ugv.sh must be running).
#
#   tools/ugv_lidar_view.sh [SECONDS] [OUT_DIR]   while a patrol drives: listen for SECONDS (default 45) and draw
#                                                lidar-back.jpg (from ahead of the robot) and lidar-side.jpg
#   tools/ugv_lidar_view.sh --sweep [OUT_DIR]     no patrol, no Jetson: move the robot along the route
#                                                (tools/ugv_lidar_sweep.py, about 8 minutes) and draw lidar-loop.jpg,
#                                                lidar-F1.jpg ... lidar-F5.jpg and lidar-single.jpg
#
# OUT_DIR defaults to run/ugv/lidar-<time>; the cloud is kept there (cloud.npz). Needs Gazebo's Python (PX4's
# gz_env.sh) and rsvg-convert (brew install librsvg).
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "${1:-}" = "--sweep" ]; then MODE=sweep; shift; OUT=${1:-}; else MODE=capture; SECS=${1:-45}; OUT=${2:-}; fi
OUT=${OUT:-$ROOT/run/ugv/lidar-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"
cd "$ROOT"
set +u; source "${PX4_DIR:-$HOME/PX4-Autopilot}/build/px4_sitl_default/gz_env.sh" >/dev/null 2>&1; set -u
export GZ_PARTITION=querra_ugv GZ_IP=127.0.0.1            # the same transport settings as ./ugv.sh
PY="$CONDA_PREFIX/bin/python"
if [ "$MODE" = sweep ]; then
  [ -f "$OUT/cloud.npz" ] || nice -n 10 "$PY" tools/ugv_lidar_sweep.py "$OUT/cloud.npz"
  VIEWS="loop $(python3 -c "import json; print(' '.join(f['id'] for f in json.load(open('worlds/forest_meta.json'))['faults']))") single"
else
  nice -n 10 "$PY" tools/ugv_lidar_capture.py "$OUT/cloud.npz" "$SECS"
  VIEWS="back side"
fi
for v in $VIEWS; do
  nice -n 10 "$PY" tools/ugv_lidar_render.py "$OUT/cloud.npz" "$OUT/$v" "$v"
  sips -s format png "$OUT/$v.ppm" --out "$OUT/$v.png" >/dev/null
  python3 tools/ugv_lidar_label.py "$OUT/$v" "$OUT/$v.svg"
  rsvg-convert "$OUT/$v.svg" -o "$OUT/$v-labeled.png"
  sips -s format jpeg -s formatOptions 84 "$OUT/$v-labeled.png" --out "$OUT/lidar-$v.jpg" >/dev/null
  rm -f "${OUT:?}/${v:?}.ppm" "${OUT:?}/${v:?}-labeled.png"
done
echo "wrote $(for v in $VIEWS; do printf '%s ' "lidar-$v.jpg"; done)in $OUT"
