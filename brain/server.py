"""Gardian brain: the Jetson looks at the farm and answers questions out loud.

Inputs   RTSP streams (mast RGB, mast thermal, drone camera) + the state API (/state)
Model    a local vision-language model through Ollama (falls back to facts-only answers)
Voice    Piper on the Jetson (or `say` on a Mac); without either the browser speaks
Page     http://<jetson>:8090  type a question, hear the answer

    python3 brain/server.py --state http://MAC:8095 --rtsp rtsp://MAC:8554 \\
        --model qwen2.5vl:7b --voice en_US-lessac-medium --voice-dir ~/voices

    python3 brain/server.py --replay scenario --model qwen2.5vl:7b ...   # a recorded run, no simulation needed

Standard library only; needs `ffmpeg` on PATH for the RTSP frames.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STREAMS = {"rgb": "ground/rgb", "thermal": "ground/thermal", "drone": "drone/cam"}
ARGS = None


# ---------------------------------------------------------------- frames
class FrameGrabber(threading.Thread):
    """Keeps the latest JPEG of one stream: an RTSP URL, or a recorded MP4 played in real time (replay)."""

    def __init__(self, name, url):
        super().__init__(daemon=True)
        self.name, self.url = name, url
        self.jpeg, self.t = None, 0.0
        self.proc = None
        self.offset = 0.0

    def restart(self, offset=0.0):
        self.offset = offset
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self):
        while True:
            if self.url.startswith("rtsp://"):
                src = ["-rtsp_transport", "tcp", "-i", self.url]
            else:
                src = ["-re", "-ss", "%.2f" % self.offset, "-i", self.url]
            cmd = [ARGS.ffmpeg, "-hide_banner", "-loglevel", "error"] + src + [
                   "-vf", "fps=2,scale=512:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"]
            try:
                proc = self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                time.sleep(5)
                continue
            buf = b""
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9", start + 2)
                    if start < 0 or end < 0:
                        break
                    self.jpeg, self.t = buf[start:end + 2], time.time()
                    buf = buf[end + 2:]
                if len(buf) > 4_000_000:
                    buf = b""
            proc.wait()
            if self.url.startswith("rtsp://"):
                time.sleep(3)  # stream not up yet, or it dropped: retry
            else:
                time.sleep(0.2)  # replay file ended or restarted: the clock decides the offset

    def fresh(self, max_age=10):
        return self.jpeg if self.jpeg and time.time() - self.t < max_age else None


GRABBERS = {}


class Replay:
    """A recorded run: videos + state timeline on one clock, looping."""

    def __init__(self, folder):
        self.folder = folder
        meta = json.load(open(os.path.join(folder, "scenario.json")))
        self.timeline = []
        with open(os.path.join(folder, "timeline.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    self.timeline.append((row["t"], row["state"]))
                except (ValueError, KeyError):
                    continue
        self.start = float(meta.get("start_s", 0.0))  # skip the warm-up at the beginning of the recording
        self.duration = (min(meta["seconds"], self.timeline[-1][0] + 0.5) if self.timeline else meta["seconds"]) - self.start
        self.t0 = time.time()

    def elapsed(self):
        return (time.time() - self.t0) % self.duration

    def state(self):
        e = self.elapsed() + self.start
        best = self.timeline[0][1] if self.timeline else None
        for t, st in self.timeline:
            if t > e:
                break
            best = st
        return best

    def restart(self, at=0.0):
        at = max(0.0, min(float(at), self.duration - 1))
        self.t0 = time.time() - at
        for g in GRABBERS.values():
            g.restart(self.start + at)

    def watch(self):
        """Restart the videos together when the scenario loops."""
        loop = 0
        while True:
            n = int((time.time() - self.t0) // self.duration)
            if n != loop:
                loop = n
                for g in GRABBERS.values():
                    g.restart(self.start)
            time.sleep(0.5)


REPLAY = None


# ---------------------------------------------------------------- facts
def get_json(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


FAULT_WORDS = {"wire_break": "broken top wire", "post_down": "fallen post", "branch_short": "branch on the wires"}


def facts_from_state(st):
    """Plain sentences the model (and the fallback) can rely on, as (topic, sentence) pairs."""
    if not st:
        return [("none", "The state API is not reachable, so I only have the camera images.")]
    out = []
    p = st["pasture"]
    out.append(("herd", "The pasture has %d animals in the herd (%d cows, %d sheep), a %d m electric fence with %d wires, and the gate is %s."
                % (p["herd_total"], p["cows"], p["sheep"], p["fence_length_m"], p["wires"], p["gate"])))
    g = st.get("ground")
    if g and not g.get("stale"):
        cams = g["by_camera"]
        out.append(("cams", "Right now my RGB camera sees %d animals, my thermal camera sees %d warm animals, and the iToF sensor at the gate sees %d."
                    % (len(cams.get("rgb", [])), len(cams.get("thermal", [])), len(cams.get("depth", [])))))
        if g["gate_out"]:
            out.append(("gate", "%d animal%s walked out through the open gate." % (g["gate_out"], "" if g["gate_out"] == 1 else "s")))
        if g["outside_seen"]:
            out.append(("outside", "My mast cameras saw these animals outside the fence: %s." % ", ".join(g["outside_seen"])))
        f = g["fence"]
        out.append(("fence", "The fence monitor reads %.1f kV at the energizer; at the far end the bottom wire has %.1f kV and the top wire %.1f kV, and the alarm is set below %.1f kV."
                    % (max(f["energizer_kv"]), f["end_kv"][0], f["end_kv"][1], f["alarm_below_kv"])))
        if f["alarms"]:
            out.append(("alarm", "There is a fence alarm on the %s wire, so the wire is broken somewhere along the fence." % " and ".join(f["alarms"])))
    else:
        out.append(("cams", "My ground-station sensors are still starting up."))
    d = st.get("drone") or {}
    phase = d.get("phase", "on_pad")
    if phase == "on_pad":
        out.append(("drone", "The drone is on its landing pad next to the barn."))
    elif phase in ("preflight", "takeoff"):
        out.append(("drone", "The drone is taking off from its pad."))
    elif phase in ("return", "landing"):
        out.append(("drone", "The drone has finished the fence loop and is %s." % ("flying back to its pad" if phase == "return" else "landing")))
    else:
        out.append(("drone", "The drone is flying along the fence at %.0f m, %.0f%% of the fence inspected so far."
                    % (d.get("alt_m", 0), d.get("fence_pct", 0))))
    if d.get("trigger") or st.get("pending_drone_request"):
        out.append(("trigger", "I sent the drone because: %s." % (d.get("trigger") or st["pending_drone_request"])))
    when = "On its last flight the drone found" if phase == "on_pad" else "So far on this flight the drone found"
    if d.get("faults_found"):
        out.append(("found_faults", "%s these fence faults: %s." % (when, "; ".join("%s, %s" % (x["id"], FAULT_WORDS.get(x["type"], x["type"])) for x in d["faults_found"]))))
    if d.get("escaped_found"):
        out.append(("found_animals", "%s these animals outside the fence: %s." % (when, ", ".join(d["escaped_found"]))))
    for ev in st.get("events", [])[-6:]:
        if ev["kind"] == "fault":
            out.append(("event", "Event: the drone found fault %s, %s, at %s, GPS %.6f, %.6f." % (ev["id"], ev.get("label", ""), ev.get("where", ""), ev["lat"], ev["lon"])))
        elif ev["kind"] == "animal":
            near = "the gate" if ev.get("near_fault") == "gate" else ev.get("near_fault", "?")
            out.append(("event", "Event: the drone found %s, a %s, %.0f m outside the fence near %s." % (ev["id"], ev.get("species", "animal"), ev.get("distance_to_fence_m", 0), near)))
        elif ev["kind"] == "gate_exit":
            out.append(("event", "Event: the gate sensor counted %s leaving through the gate." % ev["id"]))
        elif ev["kind"] == "animal_outside":
            out.append(("event", "Event: my %s camera saw %s outside the fence." % (ev.get("camera", "mast"), ev["id"])))
        elif ev["kind"] == "voltage_alarm":
            out.append(("event", "Event: fence voltage alarm, %s wire at %.1f kV at the far end." % (ev.get("wire", "?"), ev.get("kv_end", 0))))
    return out


# ---------------------------------------------------------------- answering
SYSTEM = """You are Gardian, the ground station of a farm: an NVIDIA Jetson on a pole next to the gate of an electric-fenced pasture.
You get up to three live images, in this order when present: the RGB camera on your mast, your thermal camera (bright = warm),
and the downward-tilted inspection camera of the drone. You also get FACTS from your sensors and from the drone; they are correct.
This farm is a Gazebo simulation used to develop the real system; say so if asked.
Answer in two to four short sentences that sound natural when spoken aloud. Use the FACTS for numbers, animal IDs, voltages and
positions; use the images to describe what is visible. If something is in neither, say you do not know. No lists, no markdown."""


def pick_cameras(question):
    """Only the images that matter for the question (fewer images = faster answers on the Jetson)."""
    q = question.lower()
    if any(w in q for w in ("thermal", "warm", "heat", "night", "termal")):
        return ["thermal"]
    if any(w in q for w in ("drone", "fly", "flying", "found", "inspect", "dron")):
        return ["drone"]
    if any(w in q for w in ("fence", "gate", "outside", "escape", "gard", "poart")):
        return ["rgb"]
    return ["rgb", "thermal"]


def warm_up():
    """Load the model into GPU memory at start, so the first question is not slow."""
    try:
        body = json.dumps({"model": ARGS.model, "prompt": "Ready.", "stream": False, "keep_alive": "60m",
                           "options": {"num_predict": 1}}).encode("utf-8")
        req = urllib.request.Request(ARGS.ollama + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180).read()
        print("[brain] model %s loaded" % ARGS.model, flush=True)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print("[brain] model warm-up failed: %s" % e, flush=True)


def ollama_ok():
    try:
        get_json(ARGS.ollama + "/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ask_model(question, facts, images):
    lang = "Answer in Romanian." if ARGS.lang == "ro" else "Answer in English."
    msg = {"role": "user", "content": "FACTS:\n- " + "\n- ".join(facts) + "\n\nQUESTION: " + question + "\n" + lang}
    if images:
        msg["images"] = [base64.b64encode(j).decode("ascii") for j in images]
    body = json.dumps({"model": ARGS.model, "stream": False, "keep_alive": "60m",
                       "options": {"temperature": 0.3, "num_predict": 140},
                       "messages": [{"role": "system", "content": SYSTEM}, msg]}).encode("utf-8")
    req = urllib.request.Request(ARGS.ollama + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))["message"]["content"].strip()


ROUTES = [
    (("summar", "happened", "report", "so far", "story"), ["gate", "alarm", "trigger", "found_faults", "found_animals", "drone"]),
    (("found", "find", "detect"), ["found_faults", "found_animals", "drone"]),
    (("drone", "fly", "flying", "take off", "took off"), ["drone", "trigger", "found_faults", "found_animals"]),
    (("fence", "voltage", "wire", "kv", "fault", "broken"), ["fence", "alarm", "found_faults"]),
    (("outside", "escape", "gate", "missing", "out"), ["gate", "outside", "found_animals"]),
    (("thermal", "warm", "heat", "night"), ["cams"]),
]


def facts_answer(question, facts):
    """No model available: answer from the facts, picked by the kind of question."""
    q = question.lower()
    topics = ["herd", "cams", "drone"]
    for words, route in ROUTES:
        if any(w in q for w in words):
            topics = route
            break
    by_topic = {}
    for topic, sentence in facts:
        by_topic.setdefault(topic, sentence)
    picked = [by_topic[t] for t in topics if t in by_topic][:4]
    return " ".join(picked) or "I do not have that information yet."


# ---------------------------------------------------------------- speech
AUDIO = {}


def speak(text):
    """Returns an audio id, or None when the browser should speak instead."""
    out = os.path.join(tempfile.gettempdir(), "gardian_%s.wav" % uuid.uuid4().hex[:8])
    try:
        if ARGS.piper and ARGS.voice:
            # piper-tts from pip (`piper -m VOICE -f OUT -- TEXT`); older piper binaries read the text on stdin
            base = [ARGS.piper, "-m", ARGS.voice, "-f", out] + (["--data-dir", ARGS.voice_dir] if ARGS.voice_dir else [])
            r = subprocess.run(base + ["--", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            if r.returncode != 0 or not os.path.exists(out):
                subprocess.run([ARGS.piper, "--model", ARGS.voice, "--output_file", out], input=text.encode("utf-8"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
        elif shutil.which("say"):
            subprocess.run(["say", "-o", out, "--file-format=WAVE", "--data-format=LEI16@22050", text],
                           timeout=60, check=True)
        else:
            return None
        with open(out, "rb") as f:
            data = f.read()
        os.remove(out)
    except (OSError, subprocess.SubprocessError):
        return None
    aid = uuid.uuid4().hex[:10]
    AUDIO[aid] = data
    while len(AUDIO) > 20:
        AUDIO.pop(next(iter(AUDIO)))
    return aid


# ---------------------------------------------------------------- http
LOCK = threading.Lock()


def answer(question):
    t0 = time.time()
    if REPLAY:
        st = REPLAY.state()
    else:
        try:
            st = get_json(ARGS.state + "/state")
        except (urllib.error.URLError, OSError, ValueError):
            st = None
    tagged = facts_from_state(st)
    facts = [sentence for _, sentence in tagged]
    images = [j for j in (GRABBERS[n].fresh() for n in pick_cameras(question)) if j]
    mode = "facts"
    text = None
    if ARGS.model != "none" and ollama_ok():
        try:
            with LOCK:  # one question at a time on the GPU
                text = ask_model(question, facts, images)
            mode = "vlm"
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print("[brain] model error: %s" % e, flush=True)
    if not text:
        text = facts_answer(question, tagged)
    aid = speak(text)
    return dict(answer=text, audio=("/audio/%s.wav" % aid) if aid else None, mode=mode,
                model=ARGS.model if mode == "vlm" else "facts only", images=len(images), facts=facts,
                latency_ms=round((time.time() - t0) * 1000))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path.startswith("/frame/") and path.endswith(".jpg"):
            g = GRABBERS.get(path[7:-4])
            j = g.fresh(30) if g else None
            if j:
                self._send(200, j, "image/jpeg")
            else:
                self._send(404, b"no frame yet", "text/plain")
        elif path.startswith("/audio/"):
            data = AUDIO.get(path[7:].replace(".wav", ""))
            self._send(200, data, "audio/wav") if data else self._send(404, b"gone", "text/plain")
        elif path == "/status":
            body = dict(model=ARGS.model, ollama=ollama_ok(), lang=ARGS.lang,
                        replay=dict(elapsed=round(REPLAY.elapsed()), duration=round(REPLAY.duration)) if REPLAY else None,
                        voice="piper" if (ARGS.piper and ARGS.voice) else ("say" if shutil.which("say") else "browser"),
                        frames={n: round(time.time() - g.t, 1) if g.t else None for n, g in GRABBERS.items()})
            self._send(200, json.dumps(body).encode("utf-8"), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path.startswith("/restart") and REPLAY:
            at = 0.0
            if "at=" in self.path:
                try:
                    at = float(self.path.split("at=")[1].split("&")[0])
                except ValueError:
                    at = 0.0
            REPLAY.restart(at)
            return self._send(200, b'{"ok": true}', "application/json")
        if self.path != "/ask":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        try:
            q = json.loads(self.rfile.read(n).decode("utf-8")).get("q", "").strip()
        except ValueError:
            q = ""
        if not q:
            return self._send(400, b'{"error": "empty question"}', "application/json")
        res = answer(q[:500])
        print("[brain] Q: %s\n[brain] A (%s, %d ms): %s" % (q, res["mode"], res["latency_ms"], res["answer"]), flush=True)
        self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, *args):
        pass


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="http://127.0.0.1:8095", help="state API of the simulation")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554", help="RTSP relay base URL")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen2.5vl:7b", help="Ollama vision model, or 'none' for facts-only answers")
    ap.add_argument("--piper", default=shutil.which("piper"), help="Piper binary for the voice")
    ap.add_argument("--voice", default=None, help="Piper voice: a name like en_US-lessac-medium or a path to the .onnx")
    ap.add_argument("--voice-dir", default=None, help="folder with downloaded Piper voices")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    ap.add_argument("--lang", default="en", choices=["en", "ro"])
    ap.add_argument("--replay", default=None, help="folder from tools/record_scenario.py: play a recorded run in a loop")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    ARGS = ap.parse_args()
    ARGS.state, ARGS.rtsp, ARGS.ollama = ARGS.state.rstrip("/"), ARGS.rtsp.rstrip("/"), ARGS.ollama.rstrip("/")
    global REPLAY
    files = {"rgb": "ground_rgb.mp4", "thermal": "ground_thermal.mp4", "drone": "drone_cam.mp4"}
    if ARGS.replay:
        REPLAY = Replay(ARGS.replay)
        threading.Thread(target=REPLAY.watch, daemon=True).start()
        print("[brain] replay %s: %.0f s, %d states" % (ARGS.replay, REPLAY.duration, len(REPLAY.timeline)), flush=True)
    for name, path in STREAMS.items():
        src = os.path.join(ARGS.replay, files[name]) if ARGS.replay else "%s/%s" % (ARGS.rtsp, path)
        GRABBERS[name] = FrameGrabber(name, src)
        if REPLAY:
            GRABBERS[name].offset = REPLAY.start
        GRABBERS[name].start()
    if ARGS.model != "none":
        threading.Thread(target=warm_up, daemon=True).start()
    print("[brain] http://%s:%d  model=%s  state=%s  rtsp=%s" % (ARGS.host, ARGS.port, ARGS.model, ARGS.state, ARGS.rtsp), flush=True)
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
