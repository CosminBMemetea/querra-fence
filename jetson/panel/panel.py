#!/usr/bin/env python3
"""QUERRA Fence panel v2 for the Jetson: live cameras, GPS, radar and field data collection on one page.

    python3 panel.py            # http://<jetson>:8080

The panel process is also the device hub (hub.py): the only owner of both cameras; it reads GPS through gpsd and
the radar through the ld2450-radar service. Field mode takes its USB frames and GPS fix from the hub's local QFC1
stream (127.0.0.1:5602), so live view keeps working while data is collected.
PIN protection is off by default ("require_pin" in config.json). The panel never starts field capture by itself.
"""
import hmac, json, os, re, secrets, shutil, signal, subprocess, tarfile, threading, time, urllib.parse
import hub
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)                                  # ~/querra-scout-20261107
FIELD_SH = os.path.join(SCOUT, "field.sh")
FIELD_STOP = os.path.join(SCOUT, "field-stop.sh")
SSD_RUNS = "/ssd/querra/field-runs"
EMMC_RUNS = os.path.join(SCOUT, "runs")
ENGINES = {"v0.2": "models/fence-yolo/fence-yolo11n-fp16.engine", "v0.3": "models/fence-yolo/fence-yolo11n-v0.3-fp16.engine"}
UID = os.getuid()
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{UID}", DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{UID}/bus",
           PATH="/usr/local/cuda/bin:/usr/sbin:/usr/bin:/sbin:/bin")
FIELD_CRON = (f"@reboot sleep 60 && export XDG_RUNTIME_DIR=/run/user/{UID}; systemctl --user stop querra-vision; "
              f"cd {SCOUT} && ./field.sh # querra-field")
CONFIG = os.path.join(HERE, "config.json")


DEFAULTS = {"port": 8080, "require_pin": False, "live_fps": 10, "csi_white_balance": "gray", "field_feed_port": 5602}


def load_config():
    cfg = json.load(open(CONFIG)) if os.path.exists(CONFIG) else {}
    changed = False
    for k, v in dict(DEFAULTS, pin="%06d" % secrets.randbelow(10 ** 6)).items():
        if k not in cfg:
            cfg[k] = v; changed = True
    if changed:
        json.dump(cfg, open(CONFIG, "w"), indent=1); os.chmod(CONFIG, 0o600)
    return cfg


CFG = load_config()
STATE = {"stopping": False, "last_stop": None, "last_stop_msg": "", "fails": 0, "locked_until": 0.0}
LOCK = threading.Lock()
_cache = {}


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout, env=ENV)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def cached(key, ttl, fn):
    t, v = _cache.get(key, (0, None))
    if time.time() - t > ttl:
        v = fn(); _cache[key] = (time.time(), v)
    return v


def procs():
    """(pid, argv) of all processes, read from /proc."""
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                argv = open(f"/proc/{p}/cmdline", "rb").read().split(b"\0")
                out.append((int(p), [a.decode(errors="replace") for a in argv if a]))
            except OSError:
                pass
    return out


def field_running():
    sh = cap = False
    for _, a in procs():
        if len(a) >= 2 and a[0].endswith("bash") and a[1].endswith("field.sh"):
            sh = True
        if len(a) >= 6 and a[0] == "python3" and a[2] == "jetson-launch.py" and a[3] == "run" and \
                (a[5].startswith("usb:") or a[5] == f"sim:127.0.0.1:{CFG.get('field_feed_port', 5602)}"):
            cap = True
    return sh, cap


def field_pid():
    for pid, a in procs():
        if len(a) >= 2 and a[0].endswith("bash") and a[1].endswith("field.sh"):
            return pid
    return None


def proc_age(pid):
    try:
        start = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        return float(open("/proc/uptime").read().split()[0]) - start
    except (OSError, ValueError, IndexError):
        return None


def runs_base():
    return SSD_RUNS if os.path.ismount("/ssd") and os.path.isdir(SSD_RUNS) else EMMC_RUNS


def run_dirs():
    out = []
    for base in (SSD_RUNS, EMMC_RUNS):
        if os.path.isdir(base):
            out += [os.path.join(base, d) for d in os.listdir(base) if d.startswith("field-") and os.path.isdir(os.path.join(base, d))]
    return sorted(out, key=lambda p: os.path.basename(p), reverse=True)


def tail_lines(path, n=1, block=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - block))
            return [l for l in f.read().decode(errors="replace").splitlines() if l.strip()][-n:]
    except OSError:
        return []


def count_lines(path):
    try:
        with open(path, "rb") as f:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b""))
    except OSError:
        return 0


def disk(path):
    try:
        u = shutil.disk_usage(path); return {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}
    except OSError:
        return None


def temps():
    out = {}
    for z in sorted(os.listdir("/sys/class/thermal")):
        if z.startswith("thermal_zone"):
            try:
                t = open(f"/sys/class/thermal/{z}/type").read().strip()
                if t in ("cpu-thermal", "gpu-thermal", "tj-thermal"):
                    out[t.split("-")[0]] = round(int(open(f"/sys/class/thermal/{z}/temp").read()) / 1000, 1)
            except (OSError, ValueError):
                pass
    return out


def crontab():
    rc, out = run("crontab -l")
    return out if rc == 0 else ""


def set_cron(tag, line, on):
    lines = [l for l in crontab().splitlines() if f"# {tag}" not in l and l.strip() and not l.startswith("no crontab")]
    if on:
        lines.append(line)
    p = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n" if lines else "", text=True, capture_output=True, env=ENV)
    if not lines:
        run("crontab -r")
    return p.returncode == 0


def current_model():
    s = open(FIELD_SH).read()
    for k, v in ENGINES.items():
        if v in s:
            return k
    return "?"


def field_status_file():
    st = {}
    p = os.path.join(runs_base(), "field-status.txt")
    try:
        txt = open(p).read()
        st["raw"] = txt.strip(); st["age_s"] = round(time.time() - os.path.getmtime(p))
        for line in txt.splitlines():
            if ":" in line:
                k, v = line.split(":", 1); st[k.strip().replace(" ", "_")] = v.strip()
    except OSError:
        pass
    return st


def run_summary(d, full=False):
    name = os.path.basename(d)
    dets = os.path.join(d, "detections.jsonl")
    info = {"name": name, "base": os.path.dirname(d), "alerts": count_lines(os.path.join(d, "alerts.jsonl"))}
    if full:
        key = ("sum", d, os.path.getmtime(d), os.path.getsize(dets) if os.path.exists(dets) else 0)
        def calc():
            size = 0
            for root, _, files in os.walk(d):
                for f in files:
                    try: size += os.path.getsize(os.path.join(root, f))
                    except OSError: pass
            return {"size_mb": round(size / 2**20, 1), "frames": count_lines(dets)}
        info.update(cached(key, 3600, calc))
    return info


def latest_fix(d):
    for line in reversed(tail_lines(os.path.join(d, "detections.jsonl"), 5)):
        try:
            r = json.loads(line); g = r.get("gps") or {}
            return {"status": g.get("status"), "lat": g.get("latitude"), "lon": g.get("longitude"), "time": r.get("timestamp"),
                    "detections": [f"{x['class']} {x['conf']:.2f}" for x in r.get("detections", [])][:6]}
        except (ValueError, KeyError):
            continue
    return None



# ---------------- device hub ----------------
def vision_active():
    return cached("vision", 2, lambda: run("systemctl --user is-active querra-vision")[1]) == "active"


def recorder_state():
    def get():
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:5196/api/status", headers={"Host": "127.0.0.1:5196"})
            with urllib.request.urlopen(req, timeout=0.8) as r:
                return json.loads(r.read()).get("state", "?")
        except Exception:  # noqa: BLE001
            return "not running"
    return cached("recorder", 3, get)


def cameras_allowed():
    if vision_active():
        return False, "vision"
    if recorder_state() in ("recording", "starting"):
        return False, "recorder"
    return True, ""


USB = hub.UsbCamera(live_fps=CFG["live_fps"], allowed=cameras_allowed)
CSI = hub.CsiCamera(wb=CFG["csi_white_balance"], live_fps=CFG["live_fps"], allowed=cameras_allowed)
CAMS = {"usb": USB, "csi": CSI}
GPS = hub.Gps()
RADAR = hub.Radar()
FEED = hub.FieldFeed(USB, GPS, port=CFG["field_feed_port"])
_rate = {"n": None, "t": None, "fps": 0.0}


def dir_size_mb(d):
    def calc():
        size = 0
        for root, _, files in os.walk(d):
            for f in files:
                try: size += os.path.getsize(os.path.join(root, f))
                except OSError: pass
        return round(size / 2**20, 1)
    return cached(("size", d), 5, calc)


def collection():
    sh, cap = field_running()
    dirs = run_dirs()
    cur = dirs[0] if dirs else None
    pid = field_pid()
    frames = None
    if cur:
        line = next((l for l in reversed(tail_lines(cur + ".console.log", 3)) if re.match(r"^\d{5} ", l)), None)
        frames = int(line[:5]) + 1 if line else 0
    now = time.monotonic()
    if sh or cap:
        if _rate["n"] is not None and frames is not None and frames >= _rate["n"] and now - _rate["t"] >= 1.5:
            _rate["fps"] = round((frames - _rate["n"]) / (now - _rate["t"]), 1); _rate["n"], _rate["t"] = frames, now
        elif _rate["n"] is None or (frames or 0) < _rate["n"]:
            _rate["n"], _rate["t"] = frames, now
    else:
        _rate.update(n=None, t=None, fps=0.0)
    sf = field_status_file()
    return {"running": sh or cap, "script": sh, "capture": cap, "stopping": STATE["stopping"],
            "last_stop": STATE["last_stop"], "safe_to_power_off": not (sh or cap) and not STATE["stopping"],
            "run": os.path.basename(cur) if cur else None, "run_frames": frames, "fps": _rate["fps"] if (sh or cap) else 0,
            "run_size_mb": dir_size_mb(cur) if cur else None, "run_alerts": count_lines(os.path.join(cur, "alerts.jsonl")) if cur else 0,
            "elapsed_s": round(proc_age(pid)) if pid else None, "via_hub": FEED.clients > 0,
            "waiting": (sf.get("raw", "").startswith("WAITING") or sf.get("raw", "").startswith("ERROR")) and (sh or cap),
            "status_line": sf.get("raw", "").splitlines()[0] if sf.get("raw") else "",
            "last_detections": (latest_fix(cur) or {}).get("detections", []) if cur else [],
            "autostart": "# querra-field" in crontab(), "model": current_model(), "models": list(ENGINES)}


def state():
    up = float(open("/proc/uptime").read().split()[0])
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.split(":")[0] in ("MemTotal", "MemAvailable")}
    ok, why = cameras_allowed()
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "hostname": os.uname().nodename,
        "collection": collection(),
        "cameras": {k: c.status() for k, c in CAMS.items()}, "camera_owner": "panel" if ok else why,
        "vision": vision_active(), "recorder": recorder_state(),
        "gps": GPS.state(),
        "system": {"disk": {"ssd": disk("/ssd") if os.path.ismount("/ssd") else None, "root": disk("/")}, "temps": temps(),
                   "power_mode": cached("nvp", 120, lambda: (run("nvpmodel -q")[1].splitlines() or ["?"])[0].replace("NV Power Mode:", "").strip()),
                   "uptime_s": int(up), "load": round(os.getloadavg()[0], 2),
                   "mem": {"used_gb": round((mem["MemTotal"] - mem["MemAvailable"]) / 2**20, 1), "total_gb": round(mem["MemTotal"] / 2**20, 1)},
                   "can_power_off": cached("cpo", 300, lambda: run("busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff")[1].split()[-1].strip('"'))},
        "require_pin": bool(CFG.get("require_pin")),
        "ros": ros_state(),
    }


def alerts(limit=30):
    out = []
    for d in run_dirs()[:20]:
        for line in tail_lines(os.path.join(d, "alerts.jsonl"), limit):
            try:
                a = json.loads(line); a["run"] = os.path.basename(d)
                a["maps"] = f"https://www.google.com/maps?q={a['lat']},{a['lon']}"
                out.append(a)
            except (ValueError, KeyError):
                pass
        if len(out) >= limit:
            break
    out.sort(key=lambda a: a.get("timestamp") or "", reverse=True)
    return out[:limit]


def latest_frame():
    for d in run_dirs()[:3]:
        a = os.path.join(d, "annotated")
        if os.path.isdir(a):
            fs = sorted(os.listdir(a))
            if fs:
                return os.path.join(a, fs[-1])
    return None



# ---------------- actions ----------------
def _default_signals():
    # The panel is often started with "nohup ... &", which leaves SIGINT ignored; children would inherit that and
    # field-stop.sh's SIGINT (clean finish of the current chunk) would do nothing.
    signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGQUIT, signal.SIG_DFL)


def act_start():
    sh, cap = field_running()
    if sh or cap:
        return 409, {"ok": False, "code": "already_running"}
    if STATE["stopping"]:
        return 409, {"ok": False, "code": "stopping"}
    if vision_active():
        run("systemctl --user stop querra-vision", 20); _cache.pop("vision", None)
    subprocess.Popen(["bash", "./field.sh"], cwd=SCOUT, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=_default_signals)
    return 200, {"ok": True, "code": "started"}


def act_stop():
    if STATE["stopping"]:
        return 409, {"ok": False, "code": "stopping"}
    STATE["stopping"] = True
    def worker():
        rc, out = run(["bash", FIELD_STOP], 90)
        STATE.update(stopping=False, last_stop=time.strftime("%H:%M:%S"), last_stop_msg=out.splitlines()[-1] if out else f"rc={rc}")
    threading.Thread(target=worker, daemon=True).start()
    return 200, {"ok": True, "code": "stopping"}


def act_autostart(on):
    if not set_cron("querra-field", FIELD_CRON, bool(on)):
        return 500, {"ok": False, "code": "error", "msg": "crontab failed"}
    return 200, {"ok": True, "code": "autostart_on" if on else "autostart_off"}


def act_model(v):
    if v not in ENGINES:
        return 400, {"ok": False, "code": "error", "msg": "unknown model"}
    sh, cap = field_running()
    if sh or cap:
        return 409, {"ok": False, "code": "stop_first"}
    if not os.path.exists(os.path.join(SCOUT, ENGINES[v])):
        return 404, {"ok": False, "code": "error", "msg": "engine missing: " + ENGINES[v]}
    s = open(FIELD_SH).read()
    new = re.sub(r"--detector \S+", "--detector " + ENGINES[v], s, count=1)
    if new != s:
        shutil.copy2(FIELD_SH, FIELD_SH + ".bak-panel-" + time.strftime("%Y%m%d-%H%M%S"))
        tmp = FIELD_SH + ".tmp"; open(tmp, "w").write(new); shutil.copymode(FIELD_SH, tmp); os.replace(tmp, FIELD_SH)
    return 200, {"ok": True, "code": "model_set", "msg": v}


def act_vision(on):
    """querra-vision demo owns both cameras while it runs; live view and field mode pause."""
    sh, cap = field_running()
    if on and (sh or cap):
        return 409, {"ok": False, "code": "stop_first"}
    rc, out = run(f"systemctl --user {'start' if on else 'stop'} querra-vision", 30)
    _cache.pop("vision", None)
    return (200 if rc == 0 else 500), {"ok": rc == 0, "code": ("vision_on" if on else "vision_off") if rc == 0 else "error", "msg": out[-200:]}


def act_poweroff(confirm):
    sh, cap = field_running()
    if sh or cap or STATE["stopping"]:
        return 409, {"ok": False, "code": "stop_first"}
    can = run("busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff")[1]
    if '"yes"' not in can:
        return 200, {"ok": False, "needs_sudo": True, "code": "needs_sudo", "command": "sudo poweroff"}
    if confirm != "POWEROFF":
        return 400, {"ok": False, "code": "confirm"}
    run("sync"); subprocess.Popen(["systemctl", "poweroff"], env=ENV, start_new_session=True)
    return 200, {"ok": True, "code": "powering_off"}


# ---------------- ROS 2 (Docker container querra-ros, see ros2/ros.sh) ----------------
ROS_DIR = "/ssd/querra/ros2"
ROS_SH = os.path.join(ROS_DIR, "ros.sh")
BAGS = "/ssd/querra/bags"
ROS_CRON = f"@reboot sleep 90 && {ROS_SH} start >> {ROS_DIR}/autostart.log 2>&1 # querra-ros"
ROS = {"busy": None, "record_until": 0.0, "msg": ""}


def ros_running():
    return cached("ros_run", 2, lambda: run(["docker", "inspect", "-f", "{{.State.Running}}", "querra-ros"])[1].strip()) == "true"


def ros_bags():
    out = []
    if os.path.isdir(BAGS):
        for b in sorted(os.listdir(BAGS), reverse=True)[:20]:
            d = os.path.join(BAGS, b)
            if not os.path.isdir(d):
                continue
            info = {"name": b, "size_mb": dir_size_mb(d), "duration_s": None, "messages": None}
            try:
                meta = open(os.path.join(d, "metadata.yaml")).read()
                m = re.search(r"duration:\s*\n\s*nanoseconds:\s*(\d+)", meta); info["duration_s"] = round(int(m.group(1)) / 1e9, 1) if m else None
                m = re.search(r"message_count:\s*(\d+)", meta); info["messages"] = int(m.group(1)) if m else None
            except OSError:
                info["recording"] = True
            out.append(info)
    return out


def ros_state():
    on = ros_running()
    stats = {}
    if on:
        try:
            stats = json.load(open(os.path.join(ROS_DIR, "stats.json")))
            stats["stale"] = time.time() - stats.get("t", 0) > 8
        except (OSError, ValueError):
            stats = {}
    rec = max(0, round(ROS["record_until"] - time.time()))
    return {"installed": os.path.exists(ROS_SH), "running": on, "busy": ROS["busy"], "msg": ROS["msg"],
            "recording_s": rec if ROS["busy"] == "record" else 0,
            "autostart": "# querra-ros" in crontab(), "nodes": stats.get("nodes", []), "topics": stats.get("topics", {}),
            "stale": stats.get("stale", False), "foxglove_port": 8765}


def _ros_bg(kind, cmd, timeout):
    def worker():
        rc, out = run(cmd, timeout)
        ROS.update(busy=None, msg=(out.strip().splitlines() or [f"rc={rc}"])[-1][:200]); _cache.pop("ros_run", None)
    ROS.update(busy=kind, msg=""); threading.Thread(target=worker, daemon=True).start()


def act_ros(action, body):
    if not os.path.exists(ROS_SH):
        return 404, {"ok": False, "code": "error", "msg": "ros.sh not found in " + ROS_DIR}
    if action == "autostart":
        on = bool(body.get("on"))
        return (200, {"ok": True, "code": "ros_autostart_on" if on else "ros_autostart_off"}) if set_cron("querra-ros", ROS_CRON, on) \
            else (500, {"ok": False, "code": "error", "msg": "crontab failed"})
    if ROS["busy"]:
        return 409, {"ok": False, "code": "ros_busy"}
    if action == "start":
        _ros_bg("start", ["bash", ROS_SH, "start"], 180); return 200, {"ok": True, "code": "ros_starting"}
    if action == "stop":
        _ros_bg("stop", ["bash", ROS_SH, "stop"], 60); return 200, {"ok": True, "code": "ros_stopping"}
    if action == "record":
        if not ros_running():
            return 409, {"ok": False, "code": "ros_not_running"}
        secs = max(5, min(600, int(body.get("secs") or 20)))
        ROS["record_until"] = time.time() + secs
        _ros_bg("record", ["bash", ROS_SH, "record", str(secs)], secs + 60); return 200, {"ok": True, "code": "ros_recording"}
    return 404, {"ok": False, "code": "error", "msg": "unknown action"}


class H(BaseHTTPRequestHandler):
    server_version = "QuerraPanel/2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        if not re.match(r"^/(api/(state|radar|frame)|stream/)", self.path):
            super().log_message(fmt, *a)

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def authed(self, q=None):
        if not CFG.get("require_pin"):
            return True
        if time.time() < STATE["locked_until"]:
            self.send(429, {"ok": False, "code": "locked"}); return False
        pin = self.headers.get("X-Pin") or (q or {}).get("pin", [""])[0]
        if hmac.compare_digest(str(pin), str(CFG["pin"])):
            STATE["fails"] = 0; return True
        STATE["fails"] += 1
        if STATE["fails"] >= 5:
            STATE["fails"] = 0; STATE["locked_until"] = time.time() + 60
        self.send(401, {"ok": False, "code": "bad_pin"}); return False

    def stream(self, cam):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=qframe")
        self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.end_headers()
        self.close_connection = True
        seq, end = -1, time.monotonic() + 3600
        try:
            while time.monotonic() < end:
                cam.want_view()
                with cam.cond:
                    cam.cond.wait_for(lambda: cam.live_seq != seq, timeout=1.0)
                    jpeg, s2 = cam.live, cam.live_seq
                if jpeg is None or s2 == seq:
                    continue
                seq = s2
                self.wfile.write(b"--qframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg) + jpeg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def radar_events(self):
        """Relays the ld2450-radar SSE stream (it owns /dev/ttyUSB0; it sends no CORS headers) to the page."""
        import urllib.request
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no"); self.send_header("Connection", "close"); self.end_headers()
        self.close_connection = True
        while True:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8077/events", timeout=20) as up:
                    for line in up:
                        self.wfile.write(line)
                        if line in (b"\n", b"\r\n"):
                            self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:  # noqa: BLE001  upstream down: tell the page, retry
                try:
                    self.wfile.write(b"event: offline\ndata: " + json.dumps({"error": str(e)[:120]}).encode() + b"\n\n"); self.wfile.flush()
                except OSError:
                    return
                time.sleep(3)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); p = u.path
        if p in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "static", "index.html"), "rb").read(), "text/html; charset=utf-8")
        if p.startswith("/static/") and re.fullmatch(r"/static/[\w.-]+", p):
            f = os.path.join(HERE, "static", p[8:])
            if os.path.isfile(f):
                ct = {"svg": "image/svg+xml", "png": "image/png", "json": "application/json"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
                return self.send(200, open(f, "rb").read(), ct)
        if p in ("/api/state", "/api/status"):
            return self.send(200, state())
        if p == "/api/gps":
            return self.send(200, GPS.state())
        if p == "/api/radar":
            return self.send(200, RADAR.state())
        if p == "/radar/events":
            return self.radar_events()
        m = re.fullmatch(r"/stream/(usb|csi)\.mjpg", p)
        if m:
            return self.stream(CAMS[m.group(1)])
        m = re.fullmatch(r"/api/snap/(usb|csi)\.jpg", p)
        if m:
            cam = CAMS[m.group(1)]
            for _ in range(60):
                cam.want_view()
                if cam.live is not None and time.time() - cam.live_t < 2:
                    break
                time.sleep(0.1)
            if cam.live is None:
                return self.send(503, {"ok": False, "state": cam.status()})
            return self.send(200, cam.live, "image/jpeg")
        if p == "/api/ros/bags":
            return self.send(200, ros_bags())
        m = re.fullmatch(r"/api/ros/bag/(querra-[\w-]+)\.tar", p)
        if m:
            d = os.path.join(BAGS, m.group(1))
            if not os.path.isdir(d):
                return self.send(404, {"ok": False, "msg": "no such bag"})
            self.send_response(200); self.send_header("Content-Type", "application/x-tar")
            self.send_header("Content-Disposition", f'attachment; filename="{m.group(1)}.tar"'); self.send_header("Connection", "close"); self.end_headers()
            self.close_connection = True
            try:
                with tarfile.open(fileobj=self.wfile, mode="w|") as t:   # MCAP holds JPEGs already: no gzip
                    t.add(d, arcname=m.group(1))
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if p == "/api/runs":
            return self.send(200, [run_summary(d, full=True) for d in run_dirs()[:50]])
        if p == "/api/alerts":
            return self.send(200, alerts())
        if p == "/api/frame.jpg":
            f = latest_frame()
            if not f:
                return self.send(404, {"ok": False})
            return self.send(200, open(f, "rb").read(), "image/jpeg", {"X-Frame": os.path.basename(f)})
        m = re.fullmatch(r"/api/download/(field-[\w-]+)\.tar\.gz", p)
        if m:
            if not self.authed(q):
                return
            d = next((x for x in run_dirs() if os.path.basename(x) == m.group(1)), None)
            if not d:
                return self.send(404, {"ok": False, "code": "error", "msg": "no such run"})
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{m.group(1)}.tar.gz"')
            self.send_header("Connection", "close"); self.end_headers()
            self.close_connection = True
            try:
                with tarfile.open(fileobj=self.wfile, mode="w|gz") as t:
                    t.add(d, arcname=m.group(1))
                    con = d + ".console.log"
                    if os.path.exists(con):
                        t.add(con, arcname=m.group(1) + "/console.log")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send(404, {"ok": False, "msg": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path); p = u.path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        actions = {"/api/field/start": lambda: act_start(), "/api/field/stop": lambda: act_stop(),
                   "/api/autostart": lambda: act_autostart(body.get("on")), "/api/model": lambda: act_model(body.get("version")),
                   "/api/vision": lambda: act_vision(body.get("on")), "/api/poweroff": lambda: act_poweroff(body.get("confirm")),
                   "/api/ros/start": lambda: act_ros("start", body), "/api/ros/stop": lambda: act_ros("stop", body),
                   "/api/ros/record": lambda: act_ros("record", body), "/api/ros/autostart": lambda: act_ros("autostart", body)}
        if p == "/api/login":
            if self.authed():
                self.send(200, {"ok": True})
            return
        if p not in actions:
            return self.send(404, {"ok": False, "msg": "not found"})
        if not self.authed():
            return
        with LOCK:
            code, res = actions[p]()
        self.send(code, res)


if __name__ == "__main__":
    port = int(CFG.get("port", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True

    def _term(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _term)
    print(f"QUERRA Fence panel v2 on http://0.0.0.0:{port}", flush=True)
    try:
        srv.serve_forever()
    finally:
        for c in CAMS.values():
            c._stop("off")
