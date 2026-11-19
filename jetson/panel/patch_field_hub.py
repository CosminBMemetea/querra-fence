"""field.sh / field-stop.sh: take the USB camera + GPS from the panel hub (127.0.0.1:5602) when it is running."""
import pathlib, shutil, sys
d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/home/mmx/querra-scout-20261107')
texts = {}
def sub(name, old, new):
    s = texts.setdefault(name, (d/name).read_text())
    assert s.count(old) == 1, (name, old[:60], s.count(old))
    texts[name] = s.replace(old, new)
sub('field.sh', '  if command -v fuser >/dev/null && fuser "$(readlink -f $CAM)" >/dev/null 2>&1; then',
    '  HUB=0; (exec 3<>/dev/tcp/127.0.0.1/5602) 2>/dev/null && HUB=1   # panel hub owns camera + GPS: read from it\n'
    '  if [ $HUB = 1 ]; then SRC=(--source sim:127.0.0.1:5602); G=()\n'
    '  else SRC=(--source "usb:$CAM" --usb-format MJPG --width 1280 --height 720 --fps 30); G=("${GPSARG[@]}"); fi\n'
    '  if [ $HUB = 0 ] && command -v fuser >/dev/null && fuser "$(readlink -f $CAM)" >/dev/null 2>&1; then')
sub('field.sh', '    --source usb:$CAM --usb-format MJPG --width 1280 --height 720 --fps 30 \\\n', '    "${SRC[@]}" \\\n')
sub('field.sh', '    "${GPSARG[@]}" --duration', '    "${G[@]}" --duration')
sub('field.sh', '  log "start $OUT"', '  log "start $OUT (source: ${SRC[1]})"')
P = "^python3 -s jetson-launch.py run --source (usb|sim:127\\.0\\.0\\.1:5602)"
sub('field-stop.sh', 'pkill -INT -f "^python3 -s jetson-launch.py run --source usb"\n'
    'for _ in $(seq 1 30); do pgrep -f "^python3 -s jetson-launch.py run --source usb" >/dev/null || break; sleep 1; done\n'
    'pkill -f "^python3 -s jetson-launch.py run --source usb" 2>/dev/null',
    f"P='{P}'\npkill -INT -f \"$P\"\nfor _ in $(seq 1 30); do pgrep -f \"$P\" >/dev/null || break; sleep 1; done\npkill -f \"$P\" 2>/dev/null")
for name in texts:
    b = d/(name + '.bak-20261119-hub')
    if str(d).startswith('/home/mmx') and not b.exists(): shutil.copy2(d/name, b)
for name, s in texts.items():
    (d/name).write_text(s)
print('patched', list(texts))
