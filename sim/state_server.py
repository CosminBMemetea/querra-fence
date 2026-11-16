"""Read-only state API: what the ground station and the drone know right now, as JSON.

    GET /state    ground station, drone, pasture facts and the latest events
    GET /health   "ok"

The Jetson brain (brain/server.py) reads this together with the RTSP streams. Standard library only.
Bind to 127.0.0.1 by default; `./start.sh guard --share` exposes it on the local network.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402

RUN = geo.RUN_DIR
CFG = geo.load_config()
FENCE = geo.Fence(CFG)


def read_json(name):
    try:
        with open(os.path.join(RUN, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_events(name, source, limit=40):
    out = []
    try:
        with open(os.path.join(RUN, name), encoding="utf-8") as f:
            for line in f.readlines()[-limit:]:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                ev["source"] = source
                for k in ("label", "where"):
                    if isinstance(ev.get(k), dict):
                        ev[k] = ev[k].get("en")
                out.append(ev)
    except OSError:
        pass
    return out


def state():
    now = time.time()
    ground = read_json("ground_state.json")
    if ground and now - ground.get("t", 0) > 5:
        ground = None  # the ground station is not running (or not yet): no stale data
    drone = read_json("drone_state.json")
    if drone and drone.get("phase") != "on_pad" and now - drone.get("t", 0) > 5:
        drone = dict(drone, phase="on_pad", stale=True)
    if drone is None:
        drone = dict(phase="on_pad", flights=0)
    trigger = read_json("dispatch.json")
    scenario = CFG.get("scenario", {}) if os.environ.get("GARDIAN_GROUND") else {}
    return dict(
        time=dt.datetime.now().isoformat(timespec="seconds"),
        pasture=dict(fence_length_m=round(FENCE.length), posts=len(FENCE.posts), wires=len(FENCE.heights),
                     herd_total=CFG["herd"]["cows"] + CFG["herd"]["sheep"], cows=CFG["herd"]["cows"], sheep=CFG["herd"]["sheep"],
                     gate="open" if scenario.get("gate_open") else "closed", origin=CFG["origin"]),
        ground=ground,
        drone=drone,
        pending_drone_request=trigger["label"]["en"] if trigger else None,
        events=sorted(read_events("ground_events.jsonl", "ground") + read_events("events.jsonl", "drone"),
                      key=lambda e: e.get("t_s", 0))[-40:],
    )


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/state"):
            self._send(200, json.dumps(state(), ensure_ascii=False, indent=1))
        elif self.path.startswith("/health"):
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, json.dumps({"error": "use /state"}))

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8095)
    a = ap.parse_args()
    print("[state] http://%s:%d/state" % (a.host, a.port), flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
