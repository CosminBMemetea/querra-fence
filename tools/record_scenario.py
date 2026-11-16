"""Records one guard-mode run for replay: the RTSP streams as MP4 and the state API as a timeline.

    ./start.sh guard                     # in one terminal, from the start of the scenario
    python3 tools/record_scenario.py     # in another, right away; stops after --seconds

Output in scenario/ (git-ignored): ground_rgb.mp4, ground_thermal.mp4, drone_cam.mp4, timeline.jsonl,
scenario.json. Copy the folder to the Jetson and run `brain/server.py --replay scenario`.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMS = {"ground_rgb": "ground/rgb", "ground_thermal": "ground/thermal", "drone_cam": "drone/cam"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554")
    ap.add_argument("--state", default="http://127.0.0.1:8095/state")
    ap.add_argument("--seconds", type=int, default=270)
    ap.add_argument("--out", default=os.path.join(ROOT, "scenario"))
    ap.add_argument("--ffmpeg", default=os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin", "ffmpeg")
                    if os.environ.get("CONDA_PREFIX") else (shutil.which("ffmpeg") or "ffmpeg"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    procs = {}
    t0 = time.time()
    for name, path in STREAMS.items():
        out = os.path.join(a.out, name + ".mp4")
        # copy the H.264 as it arrives; -t keeps all files the same length
        procs[name] = subprocess.Popen([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                                        "-i", "%s/%s" % (a.rtsp, path), "-c", "copy", "-an", "-t", str(a.seconds),
                                        "-movflags", "+faststart", "-y", out])
    print("[record] %d s of %s into %s" % (a.seconds, ", ".join(STREAMS), a.out), flush=True)

    n = 0
    st = None
    with open(os.path.join(a.out, "timeline.jsonl"), "w", encoding="utf-8") as tl:
        while time.time() - t0 < a.seconds:
            t = time.time() - t0
            try:
                with urllib.request.urlopen(a.state, timeout=2) as r:
                    st = json.loads(r.read().decode("utf-8"))
                tl.write(json.dumps({"t": round(t, 2), "state": st}, ensure_ascii=False) + "\n")
                n += 1
            except (OSError, ValueError):
                pass
            if n % 20 == 0:
                d = (st or {}).get("drone", {}) if n else {}
                print("[record] %3.0f s · drone %s · %d events" % (t, d.get("phase", "?"), len((st or {}).get("events", []))), flush=True)
            time.sleep(max(0.0, 0.5 - (time.time() - t0 - t) % 0.5))

    for name, p in procs.items():
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.terminate()
    with open(os.path.join(a.out, "scenario.json"), "w") as f:
        json.dump({"seconds": a.seconds, "states": n, "recorded_at": time.strftime("%Y-%m-%d %H:%M"),
                   "streams": {k: k + ".mp4" for k in STREAMS}}, f, indent=1)
    sizes = {k: round(os.path.getsize(os.path.join(a.out, k + ".mp4")) / 1e6, 1) for k in STREAMS if os.path.exists(os.path.join(a.out, k + ".mp4"))}
    print("[record] done: %d states, video MB %s" % (n, sizes), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
