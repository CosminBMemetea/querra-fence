#!/usr/bin/env bash
# Creates "Gardian Sim.command" on the Desktop: double-click it to start the simulation.
#   tools/install_launcher.sh        English
#   tools/install_launcher.sh ro     Romanian
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANG_ARG="${1:-en}"
TARGET="$HOME/Desktop/Gardian Sim.command"
cat > "$TARGET" <<LAUNCH
#!/bin/bash
# Double-click: starts Gardian X500 (Gazebo + PX4 + fence inspection mission). Ctrl+C closes everything.
cd "$ROOT" && ./start.sh --lang $LANG_ARG
LAUNCH
chmod +x "$TARGET"
echo "Created: $TARGET (language: $LANG_ARG)"
