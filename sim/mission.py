"""Misiunea de inspecție a gardului pentru X500 (PX4 SITL), prin MAVLink (pymavlink).

1. setează PX4 pentru zbor lin (viteză, accelerație, jerk, altitudini RTL)
2. urcă misiunea: decolare -> tur complet pe lângă gard -> întoarcere și aterizare
3. în zbor rulează detectorul (cameră + senzor EM, simulate) și scrie evenimentele
4. la final salvează raportul JSON + HTML în reports/ și îl deschide

Detectorul de aici folosește pozițiile reale din simulare (ground truth) ca să mimeze
ce ar găsi camera; în proiectul real îl înlocuiești cu un model YOLO pe fluxul video.
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402
import report  # noqa: E402

from pymavlink import mavutil  # noqa: E402

M = mavutil.mavlink
TTY = sys.stdout.isatty()


def c(code, s):
    return "\033[%sm%s\033[0m" % (code, s) if TTY else s


YEL, RED, GRN, DIM, BLD, CYN = "33", "31", "32", "2", "1", "36"


LOG_PATH = os.path.join(geo.RUN_DIR, "mission.log")


def say(msg, color=None):
    sys.stdout.write("\r\033[K" if TTY else "")
    print(c(color, msg) if color else msg, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


PX4_MODES = {1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED"}
PX4_AUTO = {1: "READY", 2: "TAKEOFF", 3: "LOITER", 4: "MISSION", 5: "RTL", 6: "LAND", 8: "FOLLOW", 9: "PRECLAND"}


def mode_name(cm):
    main, sub = (cm >> 16) & 0xFF, (cm >> 24) & 0xFF
    if main == 4:
        return "AUTO." + PX4_AUTO.get(sub, str(sub))
    return PX4_MODES.get(main, str(main))


class Drone:
    def __init__(self, url):
        self.m = mavutil.mavlink_connection(url, source_system=245, source_component=190)
        self.s = dict(lat=None, lon=None, alt=0.0, vx=0.0, vy=0.0, roll=0.0, pitch=0.0, yaw=0.0,
                      armed=False, mode="", landed=0, seq=0, bat=None, gps_fix=0, sats=0, home=None)
        self.texts = []
        self._hb = 0.0

    def heartbeat(self):
        """Ne prezentăm ca stație de sol (GCS), altfel PX4 refuză armarea: 'No connection to the GCS'."""
        if time.time() - self._hb > 0.8:
            self._hb = time.time()
            self.m.mav.heartbeat_send(M.MAV_TYPE_GCS, M.MAV_AUTOPILOT_INVALID, 0, 0, M.MAV_STATE_ACTIVE)

    def _update(self, msg):
        t = msg.get_type()
        s = self.s
        if t == "GLOBAL_POSITION_INT":
            s["lat"], s["lon"], s["alt"] = msg.lat / 1e7, msg.lon / 1e7, msg.relative_alt / 1000.0
            s["vx"], s["vy"] = msg.vx / 100.0, msg.vy / 100.0
        elif t == "ATTITUDE":
            s["roll"], s["pitch"], s["yaw"] = msg.roll, msg.pitch, msg.yaw
        elif t == "HEARTBEAT" and msg.get_srcComponent() == 1 and msg.type != M.MAV_TYPE_GCS:
            s["armed"] = bool(msg.base_mode & M.MAV_MODE_FLAG_SAFETY_ARMED)
            s["mode"] = mode_name(msg.custom_mode)
        elif t == "EXTENDED_SYS_STATE":
            s["landed"] = msg.landed_state
        elif t == "MISSION_CURRENT":
            s["seq"] = msg.seq
        elif t == "SYS_STATUS" and msg.battery_remaining >= 0:
            s["bat"] = msg.battery_remaining
        elif t == "GPS_RAW_INT":
            s["gps_fix"], s["sats"] = msg.fix_type, msg.satellites_visible
        elif t == "HOME_POSITION":
            s["home"] = (msg.latitude / 1e7, msg.longitude / 1e7)
        elif t == "STATUSTEXT":
            txt = msg.text.strip() if isinstance(msg.text, str) else msg.text.decode(errors="ignore").strip()
            self.texts.append((msg.severity, txt))

    def recv(self, types=None, timeout=1.0):
        end = time.time() + timeout
        while True:
            self.heartbeat()
            left = end - time.time()
            if left <= 0:
                return None
            msg = self.m.recv_match(blocking=True, timeout=min(left, 0.1))
            if msg is None:
                continue
            if msg.get_type() == "BAD_DATA":
                continue
            self._update(msg)
            if types is None or msg.get_type() in types:
                return msg

    def pump(self, seconds):
        """Citește mesaje timp de `seconds` secunde (actualizează starea)."""
        end = time.time() + seconds
        while time.time() < end:
            self.recv(["__none__"], end - time.time())

    def drain(self):
        while True:
            msg = self.m.recv_match(blocking=False)
            if msg is None:
                return
            self._update(msg)

    @property
    def ts(self):
        return self.m.target_system or 1

    def cmd(self, command, *p, wait=3.0):
        p = list(p) + [0] * (7 - len(p))
        self.m.mav.command_long_send(self.ts, 1, command, 0, *p)
        end = time.time() + wait
        while time.time() < end:
            ack = self.recv(["COMMAND_ACK"], end - time.time())
            if ack and ack.command == command:
                return ack.result
        return None

    def set_param(self, name, value):
        is_int = isinstance(value, int)
        v = struct.unpack("<f", struct.pack("<i", value))[0] if is_int else float(value)
        ptype = M.MAV_PARAM_TYPE_INT32 if is_int else M.MAV_PARAM_TYPE_REAL32
        for _ in range(3):
            self.m.mav.param_set_send(self.ts, 1, name.encode(), v, ptype)
            end = time.time() + 1.5
            while time.time() < end:
                pv = self.recv(["PARAM_VALUE"], end - time.time())
                if pv and pv.param_id == name:
                    return True
        return False

    def upload(self, items):
        m = self.m
        m.mav.mission_clear_all_send(self.ts, 1, 0)
        self.recv(["MISSION_ACK"], 2.0)
        for attempt in range(3):
            m.mav.mission_count_send(self.ts, 1, len(items), 0)
            end = time.time() + 15
            while time.time() < end:
                msg = self.recv(["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"], 2.0)
                if msg is None:
                    break
                if msg.get_type() == "MISSION_ACK":
                    if msg.type == M.MAV_MISSION_ACCEPTED:
                        return True
                    raise RuntimeError("PX4 a refuzat misiunea (cod %d)" % msg.type)
                it = items[msg.seq]
                m.mav.mission_item_int_send(self.ts, 1, msg.seq, it["frame"], it["cmd"], 0, 1,
                                            it.get("p1", 0), it.get("p2", 0), it.get("p3", 0), it.get("p4", 0),
                                            it.get("x", 0), it.get("y", 0), it.get("z", 0), 0)
        return False


def build_items(cfg, path):
    alt = cfg["mission"]["altitude_m"]
    items = []
    lat0, lon0 = geo.enu_to_gps(cfg, 0, 0)
    items.append(dict(cmd=M.MAV_CMD_NAV_TAKEOFF, frame=M.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                      x=int(lat0 * 1e7), y=int(lon0 * 1e7), z=alt, p4=float("nan")))
    items.append(dict(cmd=M.MAV_CMD_DO_CHANGE_SPEED, frame=M.MAV_FRAME_MISSION, p1=1, p2=cfg["mission"]["speed_ms"], p3=-1))
    for (x, y) in path:
        lat, lon = geo.enu_to_gps(cfg, x, y)
        items.append(dict(cmd=M.MAV_CMD_NAV_WAYPOINT, frame=M.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                          x=int(lat * 1e7), y=int(lon * 1e7), z=alt, p4=float("nan")))
    items.append(dict(cmd=M.MAV_CMD_NAV_RETURN_TO_LAUNCH, frame=M.MAV_FRAME_MISSION))
    return items


class Detector:
    """Camera fixă înclinată + senzor EM, ca pe drona reală. Folosește pozițiile adevărate din simulare."""

    def __init__(self, cfg, fence, t0):
        mc = cfg["mission"]
        self.cfg, self.fence, self.t0 = cfg, fence, t0
        self.tilt = math.radians(mc["camera_pitch_deg"])
        self.th = math.tan(math.radians(mc["camera_hfov_deg"]) / 2)
        self.tv = self.th / mc["camera_aspect"]
        self.range = mc["detect_range_m"]
        self.faults = [dict(ft, conf=0.0, found=False) for ft in cfg["faults"]]
        self.anim_conf = {}
        self.escaped = {}
        self.seen = set()
        self.seen_inside = set()
        self.em = []
        self.em_lost_reported = False
        self.events = []
        self.rnd = random.Random(5)
        self.events_path = os.path.join(geo.RUN_DIR, "events.jsonl")
        open(self.events_path, "w").close()

    def in_view(self, s, dx, dy, tx, ty, tz):
        n, e, d = ty - dy, tx - dx, s["alt"] - tz
        dist = math.sqrt(n * n + e * e + d * d)
        if dist > self.range:
            return False
        cr, sr = math.cos(s["roll"]), math.sin(s["roll"])
        cp, sp = math.cos(s["pitch"]), math.sin(s["pitch"])
        cy, sy = math.cos(s["yaw"]), math.sin(s["yaw"])
        # R = Rz(yaw) Ry(pitch) Rx(roll), body->NED; vb = R^T v
        R = [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
             [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
             [-sp, cp * sr, cp * cr]]
        vb = [R[0][i] * n + R[1][i] * e + R[2][i] * d for i in range(3)]
        ct, st = math.cos(self.tilt), math.sin(self.tilt)
        zf = vb[0] * ct + vb[2] * st
        if zf < 0.5:
            return False
        xr = vb[1]
        yd = -vb[0] * st + vb[2] * ct
        return abs(xr / zf) < self.th and abs(yd / zf) < self.tv

    def emit(self, ev):
        ev["t_s"] = round(time.time() - self.t0, 1)
        self.events.append(ev)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def step(self, s, dx, dy, dt, animals):
        if s["alt"] < 3:
            return
        fence = self.fence
        for ft in self.faults:
            if ft["found"]:
                continue
            ax, ay, fs = fence.fault_anchor(ft)
            if self.in_view(s, dx, dy, ax, ay, 0.6):
                ft["conf"] += dt * 1.4
                if ft["conf"] >= 1.0:
                    ft["found"] = True
                    ex, ey = ax + self.rnd.gauss(0, 0.5), ay + self.rnd.gauss(0, 0.5)
                    lat, lon = geo.enu_to_gps(self.cfg, ex, ey)
                    ev = dict(kind="fault", id=ft["id"], type=ft["type"], label=ft["label"], where=fence.fault_where(ft),
                              x=round(ex, 2), y=round(ey, 2), lat=round(lat, 7), lon=round(lon, 7),
                              fence_s_m=round(fs, 1), confidence=round(self.rnd.uniform(0.86, 0.97), 2))
                    self.emit(ev)
                    say("  DEFECT  %s — %s · %s · %.6f, %.6f" % (ft["id"], ft["label"], ev["where"], lat, lon), YEL + ";1")
            else:
                ft["conf"] = max(0.0, ft["conf"] - dt * 0.5)
        for a in animals:
            if not self.in_view(s, dx, dy, a["x"], a["y"], 0.9):
                continue
            self.seen.add(a["id"])
            outside = not geo.inside(fence.poly, a["x"], a["y"])
            if not outside:
                self.seen_inside.add(a["id"])
                continue
            if a["id"] in self.escaped:
                self.escaped[a["id"]].update(x=a["x"], y=a["y"])
                continue
            self.anim_conf[a["id"]] = self.anim_conf.get(a["id"], 0.0) + dt * 2.0
            if self.anim_conf[a["id"]] >= 1.0:
                ex, ey = a["x"] + self.rnd.gauss(0, 0.6), a["y"] + self.rnd.gauss(0, 0.6)
                lat, lon = geo.enu_to_gps(self.cfg, ex, ey)
                dfence = geo.dist_to_polyline(fence.poly, a["x"], a["y"])[0]
                near = min(self.cfg["faults"], key=lambda f: math.hypot(fence.fault_anchor(f)[0] - a["x"], fence.fault_anchor(f)[1] - a["y"]))
                kind_ro = "vacă" if a["kind"] == "cow" else "oaie"
                ev = dict(kind="animal", id=a["id"], species=kind_ro, x=round(ex, 2), y=round(ey, 2), lat=round(lat, 7), lon=round(lon, 7),
                          distance_to_fence_m=round(dfence, 1), near_fault=near["id"], confidence=round(self.rnd.uniform(0.88, 0.98), 2))
                self.escaped[a["id"]] = ev
                self.emit(ev)
                say("  EVADAT  %s (%s) · %.0f m în afara gardului, lângă %s · %.6f, %.6f" % (a["id"], kind_ro, dfence, near["id"], lat, lon), RED + ";1")
        # senzor EM: citește tensiunea gardului când drona e aproape de el
        fs, lateral = fence.nearest_s(dx, dy)
        if lateral < 7 and s["alt"] < 25:
            v0 = max(0.0, fence.voltage(0, fs) + self.rnd.gauss(0, 0.07))
            v1 = max(0.0, fence.voltage(1, fs) + self.rnd.gauss(0, 0.07))
            self.em.append((round(fs, 1), round(v0, 2), round(v1, 2)))
            if v1 < 0.4 and not self.em_lost_reported and any(e[2] > 1 for e in self.em):
                self.em_lost_reported = True
                say("  EM      Firul de sus nu mai are tensiune de la ~%.0f m de energizator (fir întrerupt înainte de punctul ăsta)" % fs, CYN)
                self.events.append(dict(kind="em", label="Tensiune 0 kV pe firul de sus", fence_s_m=round(fs, 1), t_s=round(time.time() - self.t0, 1)))


def read_animals():
    try:
        with open(os.path.join(geo.RUN_DIR, "animals_live.json")) as f:
            return json.load(f)["animals"]
    except (OSError, ValueError, KeyError):
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="udpin:0.0.0.0:14540")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    path = geo.mission_path(cfg, fence)
    items = build_items(cfg, path)
    herd_total = cfg["herd"]["cows"] + cfg["herd"]["sheep"]

    say("Gardian X500 · misiune inspecție gard (%d m de gard, %d puncte de traseu)" % (fence.length, len(path)), BLD)
    d = Drone(args.url)
    say("Aștept PX4 pe %s …" % args.url, DIM)
    if d.recv(["HEARTBEAT"], 120) is None:
        say("PX4 nu răspunde. Verifică run/px4.log.", RED)
        return 2
    say("PX4 conectat.", GRN)

    params = dict(MPC_XY_CRUISE=float(cfg["mission"]["speed_ms"]), MPC_ACC_HOR=2.0, MPC_JERK_AUTO=3.0, MPC_XY_TRAJ_P=0.6,
                  NAV_ACC_RAD=3.0, MIS_TAKEOFF_ALT=float(cfg["mission"]["altitude_m"]), MPC_TKO_SPEED=2.0, MPC_LAND_SPEED=0.8,
                  MPC_YAW_MODE=0, MPC_YAWRAUTO_MAX=40.0, RTL_RETURN_ALT=15.0, RTL_DESCEND_ALT=10.0,
                  NAV_RCL_ACT=0, NAV_DLL_ACT=0, COM_RCL_EXCEPT=1, SIM_BAT_MIN_PCT=20.0)
    bad = [k for k, v in params.items() if not d.set_param(k, v)]
    say("Parametri de zbor lin setați%s." % ((" (fără: " + ", ".join(bad) + ")") if bad else ""), GRN if not bad else YEL)

    say("Aștept GPS și estimatorul …", DIM)
    end = time.time() + 120
    while time.time() < end:
        d.cmd(M.MAV_CMD_REQUEST_MESSAGE, M.MAVLINK_MSG_ID_HOME_POSITION, wait=0.5)
        d.pump(1.0)
        if d.s["home"] and d.s["gps_fix"] >= 3:
            break
    say("GPS fix %d · %d sateliți · acasă la %.6f, %.6f" % (d.s["gps_fix"], d.s["sats"], *(d.s["home"] or (0, 0))), GRN)

    if not d.upload(items):
        say("Nu am putut urca misiunea.", RED)
        return 3
    say("Misiune urcată: %d comenzi (decolare, %d puncte pe lângă gard, întoarcere)." % (len(items), len(path)), GRN)

    wait_file = os.environ.get("GARDIAN_WAIT_FILE")
    if wait_file:
        say("Aștept semnalul de start (%s) …" % os.path.basename(wait_file), DIM)
        while not os.path.exists(wait_file):
            d.pump(0.5)

    armed = False
    end = time.time() + 150
    last_note = 0.0
    say("Aștept ca PX4 să permită armarea (estimatorul se stabilizează, de obicei 30–60 s) …", DIM)
    while time.time() < end and not armed:
        d.cmd(M.MAV_CMD_DO_SET_MODE, M.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4, 4)
        r = d.cmd(M.MAV_CMD_COMPONENT_ARM_DISARM, 1)
        if r == M.MAV_RESULT_ACCEPTED:
            armed = True
            break
        if time.time() - last_note > 15:
            last_note = time.time()
            reasons = [t for _, t in d.texts[-6:] if "rm" in t or "check" in t.lower() or "fail" in t.lower()]
            if reasons:
                say("  încă nu: %s" % reasons[-1], DIM)
        d.pump(2.0)
    if not armed:
        say("PX4 nu a armat. Ultimele mesaje: %s" % "; ".join(t for _, t in d.texts[-6:]), RED)
        return 4
    d.cmd(M.MAV_CMD_MISSION_START, 0, 0)
    say("Armat. Decolare la %.0f m …" % cfg["mission"]["altitude_m"], BLD)

    t0 = time.time()
    det = Detector(cfg, fence, t0)
    track = []
    dist = 0.0
    last_xy = None
    last_det = time.time()
    last_status = 0.0
    airborne = False
    animals = []
    last_anim = 0.0
    n_wp = len(items)
    try:
        while True:
            d.recv(None, 0.05)
            d.drain()
            s = d.s
            if s["lat"] is None:
                continue
            x, y = geo.gps_to_enu(cfg, s["lat"], s["lon"])
            if last_xy:
                dist += math.hypot(x - last_xy[0], y - last_xy[1])
            last_xy = (x, y)
            if s["alt"] > 2:
                airborne = True
            now = time.time()
            if now - last_anim > 0.5:
                animals = read_animals()
                last_anim = now
            if now - last_det >= 0.2:
                det.step(s, x, y, now - last_det, animals)
                last_det = now
                if not track or math.hypot(x - track[-1][0], y - track[-1][1]) > 2:
                    track.append((round(x, 1), round(y, 1)))
            if now - last_status > 0.5 and TTY:
                last_status = now
                seq = s["seq"]
                if not airborne:
                    phase = "Decolare" if s["armed"] else "Pregătire"
                elif "RTL" in s["mode"] or seq >= n_wp - 1:
                    phase = "Retur" if s["alt"] > 9 else "Aterizare"
                elif "LAND" in s["mode"]:
                    phase = "Aterizare"
                elif seq <= 2:
                    phase = "Decolare / tranzit"
                else:
                    phase = "Inspecție gard"
                pct = max(0, min(100, int(100 * (seq - 2) / max(1, len(path))))) if seq > 2 else 0
                spd = math.hypot(s["vx"], s["vy"])
                bat = ("%d%%" % s["bat"]) if s["bat"] is not None else "–"
                sys.stdout.write("\r\033[K" + c(DIM, "[%s] " % s["mode"]) + c(BLD, phase) +
                                 "  gard %3d%% · alt %4.1f m · %3.1f m/s · bat %s · defecte %d · evadate %d · văzute %d/%d" % (
                                     pct, s["alt"], spd, bat, sum(f["found"] for f in det.faults), len(det.escaped), len(det.seen), herd_total))
                sys.stdout.flush()
            if airborne and not s["armed"] and s["alt"] < 1.0:
                break
            if now - t0 > 900:
                say("Timp depășit (15 min), opresc monitorizarea.", YEL)
                break
    except KeyboardInterrupt:
        say("Oprit manual. Salvez raportul parțial.", YEL)

    duration = time.time() - t0
    say("Aterizat. Durată %d:%02d · %.0f m zburați." % (duration // 60, duration % 60, dist), GRN + ";1")
    data = dict(
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
        drone="Holybro X500 · PX4 SITL · Gazebo Harmonic",
        world="pasture",
        origin=cfg["origin"],
        mission=dict(duration_s=round(duration), distance_m=round(dist), fence_length_m=round(fence.length),
                     altitude_m=cfg["mission"]["altitude_m"], speed_ms=cfg["mission"]["speed_ms"]),
        faults=[e for e in det.events if e["kind"] == "fault"],
        escaped_animals=list(det.escaped.values()),
        em_events=[e for e in det.events if e["kind"] == "em"],
        herd=dict(total=herd_total, seen=len(det.seen), seen_inside=len(det.seen_inside), escaped=len(det.escaped),
                  not_seen=herd_total - len(det.seen)),
        em_profile=det.em[::3],
        track=track,
        fence_polygon=[list(p) for p in fence.poly],
        posts=[[round(p["x"], 2), round(p["y"], 2)] for p in fence.posts],
    )
    os.makedirs(os.path.join(geo.ROOT, "reports"), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    jpath = os.path.join(geo.ROOT, "reports", "raport_%s.json" % stamp)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    hpath = report.write_html(data, jpath.replace(".json", ".html"))
    say("Raport: %s" % hpath, BLD)
    say("  %d defecte · %d animale evadate · %d/%d animale văzute" % (len(data["faults"]), len(data["escaped_animals"]), len(det.seen), herd_total))
    if not args.no_open and not os.environ.get("GARDIAN_NO_OPEN"):
        subprocess.run(["open", hpath], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
