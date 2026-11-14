#!/usr/bin/env bash
# Oprește tot ce a pornit start.sh (și orice simulare Gazebo/PX4 rămasă agățată).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$ROOT/run"
QUIET=0; [ "${1:-}" = "--quiet" ] && QUIET=1

PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
# PX4 se oprește curat dacă îi cerem (altfel la kill dă "Abort trap")
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
[ $QUIET -eq 0 ] && echo "Simularea Gardian X500 e oprită."
exit 0
