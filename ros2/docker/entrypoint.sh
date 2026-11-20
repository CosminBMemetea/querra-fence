#!/bin/bash
# Builds the workspace mounted at /ws (only when sources changed), then runs the command.
# "Changed" means the content hash of src/ (paths + file contents), so copies that keep old mtimes (rsync -a, scp -p)
# and deleted files also trigger a build.
set -e
source /opt/ros/humble/setup.bash
cd /ws
hash=$(find src -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha1sum | sha1sum | cut -d' ' -f1)
if [ "$(cat install/.built 2>/dev/null)" != "$hash" ]; then
  colcon build --symlink-install --event-handlers console_cohesion- >/tmp/colcon.log 2>&1 || { cat /tmp/colcon.log; exit 1; }
  echo "$hash" > install/.built
fi
source /ws/install/setup.bash
exec "$@"
