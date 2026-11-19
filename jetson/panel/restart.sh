#!/usr/bin/env bash
# Restarts the QUERRA panel (does not touch field mode).
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
pkill -f "^(/usr/bin/)?python3 panel.py$"; sleep 1
setsid nohup /usr/bin/python3 panel.py >> panel.log 2>&1 < /dev/null &
sleep 1; pgrep -fa "python3 panel.py$" >/dev/null && echo "panel running on :8080"
