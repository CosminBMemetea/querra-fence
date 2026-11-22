#!/usr/bin/env bash
# Pictures of what the ground robot's LiDAR sees, from the running forest simulation (./ugv.sh must be running).
#
#   tools/ugv_lidar_view.sh [SECONDS] [OUT_DIR]     listen for SECONDS (default 45), write to OUT_DIR
#                                                  (default run/ugv/lidar-<time>)
#
# Writes lidar-back.jpg (from ahead of the robot, looking back along the strip) and lidar-side.jpg (from above, to
# the side), plus the cloud (cloud.npz). Needs Gazebo's Python (PX4's gz_env.sh) and rsvg-convert (brew install librsvg).
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECS=${1:-45}
OUT=${2:-$ROOT/run/ugv/lidar-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"
cd "$ROOT"
set +u; source "${PX4_DIR:-$HOME/PX4-Autopilot}/build/px4_sitl_default/gz_env.sh" >/dev/null 2>&1; set -u
export GZ_PARTITION=querra_ugv GZ_IP=127.0.0.1            # the same transport settings as ./ugv.sh
PY="$CONDA_PREFIX/bin/python"
nice -n 10 "$PY" tools/ugv_lidar_capture.py "$OUT/cloud.npz" "$SECS"
for v in back side; do
  nice -n 10 "$PY" tools/ugv_lidar_render.py "$OUT/cloud.npz" "$OUT/$v" "$v"
  sips -s format png "$OUT/$v.ppm" --out "$OUT/$v.png" >/dev/null
  python3 tools/ugv_lidar_label.py "$OUT/$v" "$OUT/$v.svg" "$v"
  rsvg-convert "$OUT/$v.svg" -o "$OUT/$v-labeled.png"
  sips -s format jpeg -s formatOptions 84 "$OUT/$v-labeled.png" --out "$OUT/lidar-$v.jpg" >/dev/null
  rm -f "$OUT/$v.ppm" "$OUT/$v-labeled.png"
done
echo "wrote $OUT/lidar-back.jpg and $OUT/lidar-side.jpg"
