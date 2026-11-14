#!/usr/bin/env bash
# Stops everything start.sh started (and any leftover Gazebo/PX4 simulation).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$ROOT/run"
QUIET=0; [ "${1:-}" = "--quiet" ] && QUIET=1

PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
# Ask PX4 to shut down cleanly (killing it prints "Abort trap")
pgrep -f "px4_sitl_default/bin/px4" >/dev/null && "$PX4_DIR/build/px4_sitl_default/bin/px4-shutdown" >/dev/null 2>&1 && sleep 1

for f in director px4 gz_gui gz_server; do
  [ -f "$RUN/$f.pid" ] && kill "$(cat "$RUN/$f.pid")" 2>/dev/null
  rm -f "$RUN/$f.pid"
done
pkill -f "$ROOT/sim/director.py" 2>/dev/null
pkill -f "$ROOT/sim/mission.py" 2>/dev/null
pkill -f "px4_sitl_default/bin/px4" 2>/dev/null
pkill -f "gz sim" 2>/dev/null
sleep 1
pkill -9 -f "gz sim" 2>/dev/null
pkill -9 -f "px4_sitl_default/bin/px4" 2>/dev/null
if [ $QUIET -eq 0 ]; then
  if [ "${GARDIAN_LANG:-en}" = ro ]; then echo "Simularea Gardian X500 e oprită."; else echo "Gardian X500 simulation stopped."; fi
fi
exit 0
