#!/usr/bin/env bash
# Restarts the QUERRA panel (does not touch field mode). Also used by the desktop launcher to start it.
# Waits for the old panel to exit (it releases the cameras, :5602 and :8080 on the way out) before starting the new one,
# then reports whether the new one answers.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
PORT=${PANEL_PORT:-$(python3 -c 'import json; print(json.load(open("config.json")).get("port", 8080))' 2>/dev/null || echo 8080)}
PAT="^(/usr/bin/)?python3 panel.py$"
if pgrep -f "$PAT" >/dev/null; then
  pkill -f "$PAT"
  for _ in $(seq 1 50); do pgrep -f "$PAT" >/dev/null || break; sleep 0.2; done   # up to 10 s
  pgrep -f "$PAT" >/dev/null && { echo "old panel did not exit, killing it"; pkill -9 -f "$PAT"; sleep 0.5; }
fi
setsid nohup /usr/bin/python3 panel.py >> panel.log 2>&1 < /dev/null &
for _ in $(seq 1 40); do                                                         # up to 20 s
  curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null && { echo "panel running on :$PORT"; exit 0; }
  pgrep -f "$PAT" >/dev/null || break
  sleep 0.5
done
echo "panel did not start on :$PORT; last lines of panel.log:"; tail -n 15 panel.log; exit 1
