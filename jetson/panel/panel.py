#!/usr/bin/env python3
"""QUERRA field control panel for the Jetson: one page to start and stop field mode from a phone or a laptop.

    python3 panel.py            # http://<jetson>:8080  (standard library only)

Reading status is open. Every action needs the PIN from config.json (header X-Pin, or ?pin= for downloads).
It never starts field capture on its own. Autostart at boot is a user crontab line tagged "# querra-field" and stays
off unless someone turns it on here.
"""
import hmac, json, os, re, secrets, shutil, signal, subprocess, tarfile, threading, time, urllib.parse
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


def load_config():
    if not os.path.exists(CONFIG):
        json.dump({"pin": "%06d" % secrets.randbelow(10 ** 6), "port": 8080}, open(CONFIG, "w"), indent=1)
        os.chmod(CONFIG, 0o600)
    return json.load(open(CONFIG))


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
        if len(a) >= 5 and a[0] == "python3" and a[2] == "jetson-launch.py" and a[3] == "run" and a[5:6] and a[5].startswith("usb:"):
            cap = True
    return sh, cap


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


def status():
    sh, cap = field_running()
    dirs = run_dirs()
    cur = dirs[0] if dirs else None
    up = float(open("/proc/uptime").read().split()[0])
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.split(":")[0] in ("MemTotal", "MemAvailable")}
    cron = crontab()
    st = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "field": {"running": sh or cap, "script": sh, "capture": cap, "stopping": STATE["stopping"],
                  "last_stop": STATE["last_stop"], "last_stop_msg": STATE["last_stop_msg"]},
        "safe_to_power_off": not (sh or cap) and not STATE["stopping"],
        "status_file": field_status_file(),
        "current_run": run_summary(cur) if cur else None,
        "fix": latest_fix(cur) if cur else None,
        "autostart_field": "# querra-field" in cron,
        "autostart_panel": "# querra-panel" in cron,
        "vision": cached("vision", 3, lambda: run("systemctl --user is-active querra-vision")[1]),
        "model": current_model(),
        "models": list(ENGINES),
        "disk": {"ssd": disk("/ssd") if os.path.ismount("/ssd") else None, "root": disk("/")},
        "temps": temps(),
        "power_mode": cached("nvp", 120, lambda: (run("nvpmodel -q")[1].splitlines() or ["?"])[0].replace("NV Power Mode:", "").strip()),
        "uptime_s": int(up),
        "load": os.getloadavg()[0],
        "mem": {"used_gb": round((mem["MemTotal"] - mem["MemAvailable"]) / 2**20, 1), "total_gb": round(mem["MemTotal"] / 2**20, 1)},
        "can_power_off": cached("cpo", 300, lambda: run("busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff")[1].split()[-1].strip('"')),
        "hostname": os.uname().nodename,
    }
    return st


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
        return 409, {"ok": False, "msg": "Modul teren rulează deja."}
    if STATE["stopping"]:
        return 409, {"ok": False, "msg": "Se oprește, așteaptă câteva secunde."}
    run("systemctl --user stop querra-vision", 20)
    subprocess.Popen(["bash", "./field.sh"], cwd=SCOUT, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=_default_signals)
    return 200, {"ok": True, "msg": "Modul teren pornește (camera + GPS + detector)."}


def act_stop():
    if STATE["stopping"]:
        return 409, {"ok": False, "msg": "Oprirea e deja în curs."}
    STATE["stopping"] = True
    def worker():
        rc, out = run(["bash", FIELD_STOP], 90)
        STATE.update(stopping=False, last_stop=time.strftime("%H:%M:%S"), last_stop_msg=out.splitlines()[-1] if out else f"rc={rc}")
    threading.Thread(target=worker, daemon=True).start()
    return 200, {"ok": True, "msg": "Se oprește: se închide fragmentul curent și se scriu datele pe disc."}


def act_autostart(on):
    if not set_cron("querra-field", FIELD_CRON, bool(on)):
        return 500, {"ok": False, "msg": "crontab a eșuat"}
    return 200, {"ok": True, "msg": "Pornire automată la boot: " + ("ACTIVĂ" if on else "oprită")}


def act_model(v):
    if v not in ENGINES:
        return 400, {"ok": False, "msg": "model necunoscut"}
    sh, cap = field_running()
    if sh or cap:
        return 409, {"ok": False, "msg": "Oprește întâi modul teren."}
    if not os.path.exists(os.path.join(SCOUT, ENGINES[v])):
        return 404, {"ok": False, "msg": "engine lipsă: " + ENGINES[v]}
    s = open(FIELD_SH).read()
    new = re.sub(r"--detector \S+", "--detector " + ENGINES[v], s, count=1)
    if new != s:
        shutil.copy2(FIELD_SH, FIELD_SH + ".bak-panel-" + time.strftime("%Y%m%d-%H%M%S"))
        tmp = FIELD_SH + ".tmp"; open(tmp, "w").write(new); shutil.copymode(FIELD_SH, tmp); os.replace(tmp, FIELD_SH)
    return 200, {"ok": True, "msg": f"Modelul pentru teren: {v}"}


def act_vision(on):
    sh, cap = field_running()
    if on and (sh or cap):
        return 409, {"ok": False, "msg": "Camera e folosită de modul teren. Oprește-l întâi."}
    rc, out = run(f"systemctl --user {'start' if on else 'stop'} querra-vision", 30)
    _cache.pop("vision", None)
    return (200 if rc == 0 else 500), {"ok": rc == 0, "msg": ("querra-vision pornit" if on else "querra-vision oprit") if rc == 0 else out[-200:]}


def act_poweroff(confirm):
    sh, cap = field_running()
    if sh or cap or STATE["stopping"]:
        return 409, {"ok": False, "msg": "Oprește întâi modul teren (datele trebuie scrise pe disc)."}
    can = run("busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff")[1]
    if '"yes"' not in can:
        return 200, {"ok": False, "needs_sudo": True, "msg": "Oprirea cere parola. Rulează în terminal (SSH): sudo poweroff",
                     "command": "sudo poweroff"}
    if confirm != "OPRESTE":
        return 400, {"ok": False, "msg": "confirmare lipsă"}
    run("sync"); subprocess.Popen(["systemctl", "poweroff"], env=ENV, start_new_session=True)
    return 200, {"ok": True, "msg": "Jetsonul se oprește. Așteaptă ca LED-ul să se stingă."}


class H(BaseHTTPRequestHandler):
    server_version = "QuerraPanel/1"

    def log_message(self, fmt, *a):
        if not self.path.startswith("/api/status"):
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
        if time.time() < STATE["locked_until"]:
            self.send(429, {"ok": False, "msg": "Prea multe încercări greșite. Așteaptă un minut."}); return False
        pin = self.headers.get("X-Pin") or (q or {}).get("pin", [""])[0]
        if hmac.compare_digest(str(pin), str(CFG["pin"])):
            STATE["fails"] = 0; return True
        STATE["fails"] += 1
        if STATE["fails"] >= 5:
            STATE["fails"] = 0; STATE["locked_until"] = time.time() + 60
        self.send(401, {"ok": False, "msg": "PIN greșit"}); return False

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); p = u.path
        if p in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "static", "index.html"), "rb").read(), "text/html; charset=utf-8")
        if p.startswith("/static/") and re.fullmatch(r"/static/[\w.-]+", p):
            f = os.path.join(HERE, "static", p[8:])
            if os.path.isfile(f):
                ct = {"svg": "image/svg+xml", "png": "image/png", "json": "application/json"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
                return self.send(200, open(f, "rb").read(), ct)
        if p == "/api/status":
            return self.send(200, status())
        if p == "/api/runs":
            return self.send(200, [run_summary(d, full=True) for d in run_dirs()[:50]])
        if p == "/api/alerts":
            return self.send(200, alerts())
        if p == "/api/frame.jpg":
            f = latest_frame()
            if not f:
                return self.send(404, {"ok": False})
            return self.send(200, open(f, "rb").read(), "image/jpeg", {"X-Frame": os.path.basename(f)})
        if p == "/api/ping":
            return self.send(200, {"ok": True})
        m = re.fullmatch(r"/api/download/(field-[\w-]+)\.tar\.gz", p)
        if m:
            if not self.authed(q):
                return
            d = next((x for x in run_dirs() if os.path.basename(x) == m.group(1)), None)
            if not d:
                return self.send(404, {"ok": False, "msg": "rulare inexistentă"})
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
        if p == "/api/login":
            if self.authed():
                self.send(200, {"ok": True})
            return
        actions = {"/api/field/start": lambda: act_start(), "/api/field/stop": lambda: act_stop(),
                   "/api/autostart": lambda: act_autostart(body.get("on")), "/api/model": lambda: act_model(body.get("version")),
                   "/api/vision": lambda: act_vision(body.get("on")), "/api/poweroff": lambda: act_poweroff(body.get("confirm"))}
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
    print(f"QUERRA panel on http://0.0.0.0:{port}", flush=True)
    srv.serve_forever()
