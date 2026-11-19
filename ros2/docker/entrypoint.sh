#!/bin/bash
# Builds the workspace mounted at /ws (only when sources changed), then runs the command.
set -e
source /opt/ros/humble/setup.bash
cd /ws
stamp=$(find src -type f -newer install/.built 2>/dev/null | head -1)
if [ ! -f install/.built ] || [ -n "$stamp" ]; then
  colcon build --symlink-install --event-handlers console_cohesion- >/tmp/colcon.log 2>&1 || { cat /tmp/colcon.log; exit 1; }
  touch install/.built
fi
source /ws/install/setup.bash
exec "$@"
