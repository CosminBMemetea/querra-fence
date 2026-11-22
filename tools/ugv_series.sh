#!/usr/bin/env bash
# Runs N ground-robot repeat patrols in a row, unattended, and scores each one (the 9-of-10 goal in docs/ugv.md).
#
#   tools/ugv_series.sh [N] [JETSON]      N patrols (default 8), JETSON = user@host (default mmx@192.168.1.163)
#
# Each patrol starts clean: a fresh simulation on the Mac (./ugv.sh headless, at low CPU priority) and a fresh ROS 2
# launch on the Jetson that localises against the saved map and follows the taught route (slam:=localization
# pose:=slam; teach first with slam:=mapping). A patrol that has not ended after 25 minutes counts as failed.
# Each run is scored with tools/ugv_eval.py (summary.json in its run/ugv/<time>/ folder); the series summary goes to
# run/ugv/series-<time>.txt. Ctrl+C stops both sides.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
N=${1:-8}
J=${2:-mmx@192.168.1.163}
SSH=(ssh -i "$HOME/.ssh/querra_jetson_ed25519" -o UserKnownHostsFile="$HOME/.ssh/known_hosts_querra" -o ConnectTimeout=10)
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1)
OUT="$ROOT/run/ugv/series-$(date +%Y%m%d-%H%M%S).txt"
mkdir -p "$ROOT/run/ugv"
cd "$ROOT" || exit 1

cleanup() { "${SSH[@]}" "$J" 'cd /ssd/querra/ros2 && ./ros.sh stop' >/dev/null 2>&1; ./ugv.sh stop >/dev/null 2>&1; }
trap 'echo; echo "stopping"; cleanup; exit 1' INT TERM

echo "series of $N repeat patrols, Mac $IP, Jetson $J -> $OUT" | tee "$OUT"
ok=0
for i in $(seq 1 "$N"); do
  cleanup; sleep 3
  : > run/ugv_session.log
  nice -n 10 ./ugv.sh headless > run/ugv_session.log 2>&1 &
  for _ in $(seq 1 90); do grep -q "serving the robot" run/ugv_session.log 2>/dev/null && break; sleep 2; done
  dir=$(sed -n 's/.*log \(run\/ugv\/[0-9-]*\).*/\1/p' run/ugv_session.log | head -1)
  if [ -z "$dir" ]; then echo "#$i: the simulation did not start" | tee -a "$OUT"; continue; fi
  "${SSH[@]}" "$J" "cd /ssd/querra/ros2 && ./ros.sh ugv tcp://$IP:5611 pose:=slam slam:=localization" >/dev/null 2>&1 \
    || { echo "#$i: the Jetson launch failed" | tee -a "$OUT"; continue; }
  end=$(( $(date +%s) + 1500 ))
  until grep '"src":"patrol"' "$dir/log.jsonl" 2>/dev/null | tail -1 | grep -qE '"state":"(done|blocked|stopped)"' \
        || [ "$(date +%s)" -gt "$end" ]; do sleep 5; done
  python3 tools/ugv_eval.py "$dir" --json > "$dir/eval.txt" 2>&1
  line=$(python3 - "$dir/summary.json" <<'PY'
import json, sys
try:
    p = json.load(open(sys.argv[1]))["patrols"][-1]
except (OSError, ValueError, IndexError, KeyError):
    print("no score"); sys.exit()
r, x = p["route"], p["route"]["cross_track_m"]
s = p.get("localisation_error_m", {}).get("slam", {})
print("%s | %.1f%% in %.0f s | off route p95 %s m, max %s m | SLAM median %s m, max %s m | link gaps %s | stops %s | faults in view %s" % (
    p["result"], r["completion_pct"], r["duration_s"], x["p95"], x["max"], s.get("median"), s.get("max"),
    s.get("link_gaps_over_1s"), p.get("obstacle_stops"), p.get("faults_seen")))
PY
)
  case "$line" in done*) ok=$((ok + 1)) ;; esac
  echo "#$i $(basename "$dir"): $line" | tee -a "$OUT"
done
cleanup
echo "completed the loop in $ok of $N patrols" | tee -a "$OUT"
