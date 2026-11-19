"""Records the camera stream from tools/cam_stream.py to disk, for offline detector evaluation.

    python3 tools/cam_record.py OUT_DIR [--host 127.0.0.1] [--port 5601] [--seconds 200] [--every 1]

Writes OUT_DIR/frames/NNNNNN.jpg and OUT_DIR/frames.jsonl (one line per saved frame: file, seq, sim time and the
drone telemetry: lat, lon, alt_m, heading_deg, phase). Standard library only. Stops after --seconds, on Ctrl-C,
or when the stream closes.
"""
import argparse, json, os, socket, struct, time

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=5601)
ap.add_argument("--seconds", type=float, default=200)
ap.add_argument("--every", type=int, default=1, help="keep every Nth frame")
a = ap.parse_args()
os.makedirs(os.path.join(a.out, "frames"), exist_ok=True)


def recv(s, n):
    b = bytearray()
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise EOFError
        b += c
    return bytes(b)


s = socket.create_connection((a.host, a.port), timeout=10)
log = open(os.path.join(a.out, "frames.jsonl"), "a")
t0, n, kept = time.time(), 0, 0
try:
    while time.time() - t0 < a.seconds:
        if recv(s, 4) != b"QFC1":
            raise SystemExit("bad magic")
        hl, jl = struct.unpack(">II", recv(s, 8))
        h = json.loads(recv(s, hl))
        jpeg = recv(s, jl)
        n += 1
        if n % a.every:
            continue
        f = "frames/%06d.jpg" % kept
        open(os.path.join(a.out, f), "wb").write(jpeg)
        log.write(json.dumps(dict(file=f, seq=h.get("seq"), sim_time_s=h.get("sim_time_s"), telemetry=h.get("telemetry"))) + "\n")
        kept += 1
except (EOFError, KeyboardInterrupt, socket.timeout):
    pass
print("received %d frames, saved %d in %.0f s" % (n, kept, time.time() - t0))
