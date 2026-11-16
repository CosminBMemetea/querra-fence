"""Ground station: the Jetson on a pole at the gate, watching the pasture and the fence.

It does four things and runs on its own, with or without the drone:

* sees animals outside the fence (RGB camera by day, thermal camera at night)
* counts animals going out or in through the gate (iToF depth sensor on the gate post)
* reads the fence monitor (voltage at the energizer and at the far end, per wire)
* sends the drone when something happens: writes run/dispatch.json, which `./start.sh guard` picks up

In the simulation the "eyes" use the true animal positions inside each camera's field of view
(SimEyes), like the drone's detector. On the real Jetson, SimEyes is replaced by a model running
on the RTSP streams (the same URLs the simulation publishes: /ground/rgb, /ground/thermal, /ground/depth),
and the fence monitor by the alarm contact of a commercial fence monitor.

Output: terminal lines (GARDIAN_LANG en/ro) and run/ground_events.jsonl (always English).
"""
import json
import math
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim"))
import geo  # noqa: E402
import i18n  # noqa: E402
from i18n import t  # noqa: E402

RUN = geo.RUN_DIR
EVENTS = os.path.join(RUN, "ground_events.jsonl")
DISPATCH = os.path.join(RUN, "dispatch.json")
FLIGHT_ACTIVE = os.path.join(RUN, "flight_active")
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def say(key, **kw):
    """Same convention as the mission: terminal in the chosen language."""
    def resolved(lang):
        return {k: (i18n.pick(v, lang) if isinstance(v, tuple) else v) for k, v in kw.items()}
    print(t(key, **resolved(i18n.LANG)), flush=True)


class SimEyes:
    """Perception in the simulation: true positions filtered by each camera's field of view."""

    def __init__(self, station):
        self.cams = station["cams"]

    def animals(self):
        try:
            with open(os.path.join(RUN, "animals_live.json")) as f:
                return json.load(f)["animals"]
        except (OSError, ValueError, KeyError):
            return []

    def seen_by(self, a):
        return [name for name, cam in self.cams.items() if geo.in_camera_view(cam, a["x"], a["y"], 0.9)]


class FenceMonitor:
    """Voltage at the energizer and at the far end of the fence, per wire (simulated)."""

    def __init__(self, fence, t0):
        self.fence, self.t0 = fence, t0

    def read(self):
        el = time.time() - self.t0
        f = self.fence
        return dict(energizer=[f.voltage(s, 0.0, el) for s in (0, 1)],
                    end=[f.voltage(s, f.length, el) for s in (0, 1)])


def side_of_gate(gate, x, y):
    """>0 outside the fence line at the gate, <0 inside."""
    (gx, gy), (ox, oy) = gate["center"], gate["out"]
    return (x - gx) * ox + (y - gy) * oy


def main():
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    station = geo.ground_station(cfg, fence)
    gate = station["gate"]
    eyes = SimEyes(station)
    t0 = time.time()
    monitor = FenceMonitor(fence, t0)
    thr = station["alarm_kv"]
    os.makedirs(RUN, exist_ok=True)
    open(EVENTS, "w").close()

    reported_outside = set()
    last_side = {}
    gate_out = 0
    volt_alarm = {0: False, 1: False}
    last_status = 0.0
    dispatched_reasons = set()
    say("g_start", cams="RGB · thermal · iToF", kv=thr)

    def emit(ev):
        ev["t_s"] = round(time.time() - t0, 1)
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def dispatch(reason, x=None, y=None):
        if reason in dispatched_reasons:
            return
        dispatched_reasons.add(reason)
        if os.path.exists(FLIGHT_ACTIVE) or os.path.exists(DISPATCH):
            say("g_busy")
            return
        say("g_dispatch", reason=i18n.REASON[reason])
        tmp = DISPATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(reason=reason, label=i18n.both(i18n.REASON[reason]), x=x, y=y,
                           t_s=round(time.time() - t0, 1)), f, ensure_ascii=False)
        os.replace(tmp, DISPATCH)

    while running:
        now = time.time()
        animals = eyes.animals()
        in_view = 0
        for a in animals:
            cams = eyes.seen_by(a)
            if cams:
                in_view += 1
            # gate crossing, seen by the iToF on the gate post
            if "depth" in cams:
                side = side_of_gate(gate, a["x"], a["y"])
                prev = last_side.get(a["id"])
                if prev is not None and prev < -0.5 and side > 0.5:
                    gate_out += 1
                    say("g_gate", id=a["id"], dir=i18n.DIRECTION["out"], n=gate_out)
                    emit(dict(kind="gate_exit", id=a["id"], species=a["kind"], x=a["x"], y=a["y"]))
                    dispatch("gate_exit", a["x"], a["y"])
                if abs(side) > 0.5:
                    last_side[a["id"]] = side
            # animal outside the fence, seen by the mast cameras
            mast = [c for c in cams if c in ("rgb", "thermal")]
            if mast and a["id"] not in reported_outside and not geo.inside(fence.poly, a["x"], a["y"]):
                if geo.dist_to_polyline(fence.poly, a["x"], a["y"])[0] > 1.5:
                    reported_outside.add(a["id"])
                    dist = math.hypot(a["x"] - gate["center"][0], a["y"] - gate["center"][1])
                    say("g_outside", id=a["id"], species=i18n.SPECIES[a["kind"]], dist=dist, cam=i18n.CAM[mast[0]])
                    emit(dict(kind="animal_outside", id=a["id"], species=a["kind"], x=a["x"], y=a["y"], camera=mast[0]))
                    dispatch("animal_outside", a["x"], a["y"])
        # fence monitor
        v = monitor.read()
        for strand in (0, 1):
            low = v["end"][strand] < thr
            if low and not volt_alarm[strand]:
                say("g_volt", wire=i18n.WIRE[strand], kv=v["end"][strand], thr=thr)
                emit(dict(kind="voltage_alarm", wire=["bottom", "top"][strand], kv_end=round(v["end"][strand], 2),
                          kv_energizer=round(v["energizer"][strand], 2)))
                dispatch("voltage")
            volt_alarm[strand] = low
        if now - last_status > 30:
            last_status = now
            end = " / ".join("%.1f kV" % x for x in v["end"])
            say("g_status", n=in_view, e=max(v["energizer"]), end=end)
        time.sleep(0.25)


if __name__ == "__main__":
    sys.exit(main())
