#!/usr/bin/env bash
# QUERRA ground robot (UGV): a fenced forest enclosure in Gazebo with the patrol robot, served to the Jetson.
#
#   ./ugv.sh             Gazebo window + the robot relay on tcp://<this-mac>:5611
#   ./ugv.sh headless    without the Gazebo window (lightest on a laptop)
#   ./ugv.sh stop        stop a simulation left running
#
# Then on the Jetson:   cd /ssd/querra/ros2 && ./ros.sh ugv tcp://<this-mac>:5611
# (pose:=truth drives on the simulator's ground truth, to test the chain; the default drives on wheel odometry.)
# The world comes from forest.json (sim/gen_forest.py regenerates it on every start). Ctrl+C stops everything.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
RUN="$ROOT/run"
mkdir -p "$RUN"
MODE=${1:-gui}

stop_all() {
  for f in ugv_relay ugv_gz_gui ugv_gz_server; do
    [ -f "$RUN/$f.pid" ] && kill "$(cat "$RUN/$f.pid")" 2>/dev/null
    rm -f "$RUN/$f.pid"
  done
  pkill -f "gz sim .*worlds/forest.sdf" 2>/dev/null
  pkill -f "gz sim -g.*querra_ugv" 2>/dev/null
  return 0
}
case "$MODE" in
  stop) stop_all; echo "ugv simulation stopped"; exit 0 ;;
  gui|headless) ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac

GZ_ENV="$PX4_DIR/build/px4_sitl_default/gz_env.sh"
[ -f "$GZ_ENV" ] || { echo "Missing $GZ_ENV (Gazebo comes with PX4: cd $PX4_DIR && make px4_sitl gz_x500)"; exit 1; }
set +u; source "$GZ_ENV"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=querra_ugv     # isolated from the drone simulation (gardian)
export GZ_IP=127.0.0.1
stop_all
trap 'echo; stop_all; echo "ugv simulation stopped"; exit 0' INT TERM

"$CONDA_PREFIX/bin/python" "$ROOT/sim/gen_forest.py" || exit 1
gz sim -r -s --verbose=1 "$ROOT/worlds/forest.sdf" > "$RUN/ugv_gz_server.log" 2>&1 &
echo $! > "$RUN/ugv_gz_server.pid"
for _ in $(seq 1 60); do gz topic -l 2>/dev/null | grep -q "^/world/forest/clock" && break; sleep 1; done
gz topic -l 2>/dev/null | grep -q "^/world/forest/clock" || { echo "Gazebo did not start: see $RUN/ugv_gz_server.log"; stop_all; exit 1; }
if [ "$MODE" = gui ]; then
  gz sim -g > "$RUN/ugv_gz_gui.log" 2>&1 &
  echo $! > "$RUN/ugv_gz_gui.pid"
fi
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<this-mac>")
echo "forest world running. On the Jetson:  cd /ssd/querra/ros2 && ./ros.sh ugv tcp://$IP:5611"
"$CONDA_PREFIX/bin/python" -u "$ROOT/tools/ugv_relay.py" &
echo $! > "$RUN/ugv_relay.pid"
wait "$(cat "$RUN/ugv_relay.pid")"
stop_all
