#!/usr/bin/env bash
# Gardian X500: starts everything (Gazebo with the pasture and electric fence, PX4 on the X500,
# the animals and the inspection mission).
#
#   ./start.sh            automatic fence inspection flight + report (default)
#   ./start.sh manual     simulation only; the PX4 console (pxh>) stays here for your own commands
#   ./start.sh headless   like the default, without the Gazebo window (lightest on a laptop)
#   ./start.sh mission    only the inspection flight, on a simulation that is already running
#   ./start.sh demo       a filmed flight that regenerates docs/media (README images)
#
#   --lang ro             terminal and report in Romanian (or GARDIAN_LANG=ro); English by default
#
# Ctrl+C or ./stop.sh stops everything.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
RUN="$ROOT/run"
mkdir -p "$RUN" "$ROOT/reports"

MODE=auto
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) export GARDIAN_LANG="${2:-en}"; shift 2 ;;
    --lang=*) export GARDIAN_LANG="${1#--lang=}"; shift ;;
    auto|manual|demo) MODE="$1"; shift ;;
    headless|fara-gui) MODE=headless; shift ;;
    mission|misiune) MODE=mission; shift ;;
    *) echo "Usage: ./start.sh [auto|manual|headless|mission|demo] [--lang en|ro]"; exit 1 ;;
  esac
done
export GARDIAN_LANG="${GARDIAN_LANG:-en}"
[ "$MODE" = demo ] && export GARDIAN_LANG=en   # demo media and logs are always English

B=$'\033[1m'; Y=$'\033[33m'; G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
tr2() { if [ "$GARDIAN_LANG" = ro ]; then printf "%s" "$2"; else printf "%s" "$1"; fi; }
step() { printf "%s▸ %s%s\n" "$B" "$(tr2 "$1" "$2")" "$N"; }
info() { printf "%s  %s%s\n" "$D" "$(tr2 "$1" "$2")" "$N"; }
fail() { printf "%s✗ %s%s\n" "$R" "$(tr2 "$1" "$2")" "$N"; "$ROOT/stop.sh" --quiet; exit 1; }

PX4_BIN="$PX4_DIR/build/px4_sitl_default/bin/px4"
GZ_ENV="$PX4_DIR/build/px4_sitl_default/gz_env.sh"
PY="$PX4_DIR/.venv/bin/python"
[ -x "$PX4_BIN" ] || fail "PX4 is not built. Run once: cd $PX4_DIR && make px4_sitl" \
                         "Nu găsesc PX4 compilat. Rulează o dată: cd $PX4_DIR && make px4_sitl"
[ -f "$GZ_ENV" ] || fail "Missing $GZ_ENV (run once: cd $PX4_DIR && make px4_sitl gz_x500)" \
                         "Lipsește $GZ_ENV (rulează o dată: cd $PX4_DIR && make px4_sitl gz_x500)"
[ -x "$PY" ] || fail "Missing the PX4 Python environment ($PX4_DIR/.venv)" \
                     "Lipsește mediul Python al PX4 ($PX4_DIR/.venv)"

printf "\n%s  Gardian X500 · %s%s\n\n" "$B$Y" "$(tr2 "electric fence inspection simulation" "simulare inspecție gard electric")" "$N"

if [ "$MODE" = mission ]; then
  exec "$PY" "$ROOT/sim/mission.py"
fi

"$ROOT/stop.sh" --quiet
rm -f "$RUN/events.jsonl"
if [ "$MODE" = demo ]; then
  export GARDIAN_DEMO=1 GARDIAN_NO_OPEN=1 GARDIAN_WAIT_FILE="$RUN/demo_go"
  rm -rf "$RUN/demo_go" "$ROOT/docs/media/raw" "$RUN/mission.log"
fi
trap '"$ROOT/stop.sh"; exit 0' INT TERM

# Gazebo environment from PX4 (Tools/setup/macos/.pixi) + this project's models
# shellcheck disable=SC1090
set +u; source "$GZ_ENV"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=gardian     # isolated from other simulations
export GZ_IP=127.0.0.1          # local transport only, faster startup
command -v gz >/dev/null || fail "gz is not on PATH after gz_env.sh" "gz nu e în PATH după gz_env.sh"

step "Generating the pasture from fence.json" "Generez pășunea din fence.json"
"$PY" "$ROOT/sim/gen_world.py" || fail "gen_world.py failed" "gen_world.py a eșuat"

step "Starting Gazebo" "Pornesc Gazebo"
gz sim -r -s --verbose=1 "$ROOT/worlds/pasture.sdf" > "$RUN/gz_server.log" 2>&1 &
echo $! > "$RUN/gz_server.pid"; disown
for _ in $(seq 1 80); do
  gz topic -l 2>/dev/null | grep -q "^/world/pasture/clock" && break
  sleep 0.5
done
gz topic -l 2>/dev/null | grep -q "^/world/pasture/clock" || fail "Gazebo did not start. See $RUN/gz_server.log" \
                                                                  "Gazebo nu a pornit. Vezi $RUN/gz_server.log"
info "world 'pasture' is running" "lumea 'pasture' rulează"

if [ "$MODE" != headless ]; then
  step "Opening the Gazebo window" "Deschid fereastra Gazebo"
  gz sim -g --gui-config "$ROOT/config/gui.config" > "$RUN/gz_gui.log" 2>&1 &
  echo $! > "$RUN/gz_gui.pid"; disown
fi

step "Starting the animals, follow camera and markers" "Pornesc animalele, camera urmăritoare și marcajele"
"$CONDA_PREFIX/bin/python" "$ROOT/sim/director.py" > "$RUN/director.log" 2>&1 &
echo $! > "$RUN/director.pid"; disown

export PX4_SYS_AUTOSTART=4014 PX4_GZ_STANDALONE=1 PX4_GZ_WORLD=pasture PX4_GZ_MODEL_NAME=x500_fence

if [ "$MODE" = manual ]; then
  step "Starting PX4 (the pxh> console stays here)" "Pornesc PX4 (consola pxh> rămâne aici)"
  info "Examples: commander takeoff · commander land · commander mode auto:mission · shutdown" \
       "Exemple: commander takeoff · commander land · commander mode auto:mission · shutdown"
  info "Start the automatic mission from another terminal with: ./start.sh mission" \
       "Misiunea automată o pornești din alt terminal cu: ./start.sh mission"
  "$PX4_BIN"
  "$ROOT/stop.sh"
  exit 0
fi

step "Starting PX4 on the X500" "Pornesc PX4 pe X500"
"$PX4_BIN" -d > "$RUN/px4.log" 2>&1 &
echo $! > "$RUN/px4.pid"; disown

if [ "$MODE" = demo ]; then
  step "Demo mode: filming the flight for docs/media" "Mod demo: filmez zborul pentru docs/media"
  "$CONDA_PREFIX/bin/python" "$ROOT/tools/capture_demo.py" > "$RUN/capture.log" 2>&1 &
  CAP=$!
  "$PY" "$ROOT/sim/mission.py"
  wait $CAP
  step "Building the demo images" "Fac imaginile demo"
  "$PY" "$ROOT/tools/make_media.py" | tee "$RUN/make_media.log"
  "$ROOT/stop.sh"
  exit 0
fi

while true; do
  printf "\n"
  "$PY" "$ROOT/sim/mission.py"
  rc=$?
  [ $rc -ne 0 ] && printf "%s%s%s\n" "$Y" "$(tr2 "The mission stopped with code $rc. Logs: $RUN" "Misiunea s-a oprit cu codul $rc. Loguri: $RUN")" "$N"
  printf "\n%s%s%s %s\n" "$G" "$(tr2 "The simulation is still running." "Simularea e încă pornită.")" "$N" \
         "$(tr2 "Enter = new flight · Ctrl+C = close everything" "Enter = zbor nou · Ctrl+C = închide tot")"
  read -r || break
done
"$ROOT/stop.sh"
