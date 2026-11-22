#!/usr/bin/env bash
# The ground robot's SLAM map against the true forest. SLAM must be running on the Jetson
# (./ros.sh ugv tcp://<mac>:5611 slam:=localization pose:=slam patrol:=false is enough; ./ugv.sh on the Mac).
#
#   tools/ugv_slam_map.sh [JETSON] [OUT_DIR]     JETSON = user@host (default mmx@192.168.1.163),
#                                               OUT_DIR default run/ugv/slam-map-<time>
#
# Copies ros2/grab_map.py to the Jetson, saves /map there (compressed), fetches it with the taught route, and draws
# slam-map.svg and slam-map.png (tools/ugv_slam_map.py). Needs Gazebo's Python (numpy) and rsvg-convert.
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
J=${1:-mmx@192.168.1.163}
OUT=${2:-$ROOT/run/ugv/slam-map-$(date +%Y%m%d-%H%M%S)}
K=(-i "$HOME/.ssh/querra_jetson_ed25519" -o UserKnownHostsFile="$HOME/.ssh/known_hosts_querra" -o ConnectTimeout=10)
mkdir -p "$OUT"
scp -q "${K[@]}" "$ROOT/ros2/grab_map.py" "$J:/ssd/querra/ros2/grab_map.py"
ssh "${K[@]}" "$J" "docker exec querra-ros bash -lc 'source /ws/install/setup.bash && python3 /ws/grab_map.py /ws/maps/grid_latest.npz'"
scp -q "${K[@]}" "$J:/ssd/querra/ros2/maps/grid_latest.npz" "$J:/ssd/querra/ros2/maps/forest.route.json" "$OUT/"
set +u; source "${PX4_DIR:-$HOME/PX4-Autopilot}/build/px4_sitl_default/gz_env.sh" >/dev/null 2>&1; set -u
cd "$ROOT"
nice -n 10 "$CONDA_PREFIX/bin/python" tools/ugv_slam_map.py "$OUT/grid_latest.npz" "$OUT/forest.route.json" "$OUT/slam-map.svg"
rsvg-convert -w 1600 "$OUT/slam-map.svg" -o "$OUT/slam-map.png"
echo "wrote $OUT/slam-map.png"
