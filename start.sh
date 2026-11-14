#!/usr/bin/env bash
# Gardian X500: pornește tot (Gazebo cu pășunea și gardul electric, PX4 pe X500, animalele, misiunea).
#
#   ./start.sh            zbor automat de inspecție a gardului + raport la final (implicit)
#   ./start.sh manual     doar simularea; consola PX4 (pxh>) rămâne aici ca să dai comenzi tu
#   ./start.sh fara-gui   ca "auto", dar fără fereastra Gazebo (cel mai ușor pentru laptop)
#   ./start.sh misiune    doar zborul de inspecție, pe o simulare deja pornită (ex. din modul manual)
#   ./start.sh demo       un zbor filmat: refă imaginile din docs/media (pentru README)
#
# Totul se oprește cu Ctrl+C sau cu ./stop.sh.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
MODE="${1:-auto}"
RUN="$ROOT/run"
mkdir -p "$RUN" "$ROOT/reports"

B=$'\033[1m'; Y=$'\033[33m'; G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
step() { printf "%s▸ %s%s\n" "$B" "$*" "$N"; }
info() { printf "%s  %s%s\n" "$D" "$*" "$N"; }
fail() { printf "%s✗ %s%s\n" "$R" "$*" "$N"; "$ROOT/stop.sh" --quiet; exit 1; }

case "$MODE" in auto|manual|fara-gui|misiune|demo) ;; *) echo "Folosire: ./start.sh [auto|manual|fara-gui|misiune|demo]"; exit 1;; esac

PX4_BIN="$PX4_DIR/build/px4_sitl_default/bin/px4"
GZ_ENV="$PX4_DIR/build/px4_sitl_default/gz_env.sh"
PY="$PX4_DIR/.venv/bin/python"
[ -x "$PX4_BIN" ] || fail "Nu găsesc PX4 compilat. Rulează o dată: cd $PX4_DIR && make px4_sitl"
[ -f "$GZ_ENV" ] || fail "Lipsește $GZ_ENV (rulează o dată: cd $PX4_DIR && make px4_sitl gz_x500)"
[ -x "$PY" ] || fail "Lipsește mediul Python al PX4 ($PX4_DIR/.venv)"

printf "\n%s  Gardian X500 · simulare inspecție gard electric%s\n\n" "$B$Y" "$N"

if [ "$MODE" = "misiune" ]; then
  exec "$PY" "$ROOT/sim/mission.py"
fi

"$ROOT/stop.sh" --quiet
rm -f "$RUN/events.jsonl"
if [ "$MODE" = "demo" ]; then
  export GARDIAN_DEMO=1 GARDIAN_NO_OPEN=1 GARDIAN_WAIT_FILE="$RUN/demo_go"
  rm -rf "$RUN/demo_go" "$ROOT/docs/media/raw" "$RUN/mission.log"
fi
trap '"$ROOT/stop.sh"; exit 0' INT TERM

# Mediul Gazebo din PX4 (Tools/setup/macos/.pixi) + modelele proiectului
# shellcheck disable=SC1090
set +u; source "$GZ_ENV"; set -u
export GZ_SIM_RESOURCE_PATH="$ROOT/models:$ROOT/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_PARTITION=gardian     # izolat de alte simulări
export GZ_IP=127.0.0.1          # transport doar local, pornire mai rapidă
command -v gz >/dev/null || fail "gz nu e în PATH după gz_env.sh"

step "Generez pășunea din fence.json"
"$PY" "$ROOT/sim/gen_world.py" || fail "gen_world.py a eșuat"

step "Pornesc Gazebo"
gz sim -r -s --verbose=1 "$ROOT/worlds/pasture.sdf" > "$RUN/gz_server.log" 2>&1 &
echo $! > "$RUN/gz_server.pid"; disown
for _ in $(seq 1 80); do
  gz topic -l 2>/dev/null | grep -q "^/world/pasture/clock" && break
  sleep 0.5
done
gz topic -l 2>/dev/null | grep -q "^/world/pasture/clock" || fail "Gazebo nu a pornit. Vezi $RUN/gz_server.log"
info "lumea 'pasture' rulează"

if [ "$MODE" != "fara-gui" ]; then
  step "Deschid fereastra Gazebo"
  gz sim -g --gui-config "$ROOT/config/gui.config" > "$RUN/gz_gui.log" 2>&1 &
  echo $! > "$RUN/gz_gui.pid"; disown
fi

step "Pornesc animalele, camera urmăritoare și marcajele"
"$CONDA_PREFIX/bin/python" "$ROOT/sim/director.py" > "$RUN/director.log" 2>&1 &
echo $! > "$RUN/director.pid"; disown

export PX4_SYS_AUTOSTART=4014 PX4_GZ_STANDALONE=1 PX4_GZ_WORLD=pasture PX4_GZ_MODEL_NAME=x500_fence

if [ "$MODE" = "manual" ]; then
  step "Pornesc PX4 (consola pxh> rămâne aici)"
  info "Exemple: commander takeoff · commander land · commander mode auto:mission · shutdown"
  info "Misiunea automată o poți porni din alt terminal cu: ./start.sh misiune"
  "$PX4_BIN"
  "$ROOT/stop.sh"
  exit 0
fi

step "Pornesc PX4 pe X500"
"$PX4_BIN" -d > "$RUN/px4.log" 2>&1 &
echo $! > "$RUN/px4.pid"; disown

if [ "$MODE" = "demo" ]; then
  step "Mod demo: filmez zborul pentru docs/media"
  "$CONDA_PREFIX/bin/python" "$ROOT/tools/capture_demo.py" > "$RUN/capture.log" 2>&1 &
  CAP=$!
  "$PY" "$ROOT/sim/mission.py"
  wait $CAP
  step "Fac imaginile demo"
  "$PY" "$ROOT/tools/make_media.py" | tee "$RUN/make_media.log"
  "$ROOT/stop.sh"
  exit 0
fi

while true; do
  printf "\n"
  "$PY" "$ROOT/sim/mission.py"
  rc=$?
  [ $rc -ne 0 ] && printf "%sMisiunea s-a oprit cu codul %d. Loguri: %s%s\n" "$Y" "$rc" "$RUN" "$N"
  printf "\n%sSimularea e încă pornită.%s Enter = zbor nou · Ctrl+C = închide tot\n" "$G" "$N"
  read -r || break
done
"$ROOT/stop.sh"
