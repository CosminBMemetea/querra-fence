#!/usr/bin/env bash
# Creates "Gardian Sim.command" on the Desktop: double-click it to start the simulation.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$HOME/Desktop/Gardian Sim.command"
cat > "$TARGET" <<LAUNCH
#!/bin/bash
# Double-click: starts Gardian X500 (Gazebo + PX4 + fence inspection mission). Ctrl+C closes everything.
cd "$ROOT" && ./start.sh
LAUNCH
chmod +x "$TARGET"
echo "Created: $TARGET"
