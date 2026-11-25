"""Runs a fence detector over a drone video, such as one filmed with the DJI Mini 4 Pro, and raises alerts the way
the Jetson does in flight.

    ~/.querra-train-venv/bin/python tools/video_eval.py VIDEO.MP4 [--model MODEL.pt] [--out DIR] [--pitch 55]
        [--start S] [--end S] [--srt FILE | --no-srt] [--fps 15] [--width 1280] [--hfov 69.7] [--no-video]

As in flight: the video is decoded at --fps (15, the drone camera's rate) and --width (1280, the field camera's),
the detector keeps boxes from conf 0.35, and an alert needs the same fault class at conf 0.7 or more in 5 of the
last 8 frames (tools/confirm.py, the Jetson's alert_confirm).

With DJI's subtitle file (VIDEO.SRT next to the video; DJI Fly: camera settings, "Video Subtitles" on), each box is
placed on the ground from the drone's GPS, its height above the take-off point and its course, so the 5 sightings
must lie within 5 m of each other and every alert gets a position, as in flight. The SRT has no heading and no
gimbal angle: the heading is the course over ground (fly forward with the camera ahead, like the simulated drone),
and --pitch is the gimbal angle you flew with, in degrees below the horizon. Frames below --min-alt (take-off,
landing) do not count. Without the SRT, 5 of 8 consecutive frames confirm an alert, and sightings of one class less
than --merge-s seconds apart belong to the same alert.

The lens: the Mini 4 Pro's covers 82.1 deg diagonally on a 4:3 sensor, so 16:9 video from the full sensor width
covers 69.7 deg across (--hfov), close to the simulated drone camera's 69.0 deg. Set --hfov for a cropped mode.

Writes to --out (default run/video/<video name>/):
  annotated.mp4     every box; fault boxes that count toward an alert are thick; a new alert shows for 2 s
  detections.jsonl  one line per frame: time, position, boxes
  alerts.json       the alerts: time, class, best confidence, frames, and with the SRT the position and a map link
  alerts/           the frame that confirmed each alert
"""
import argparse
import bisect
import collections
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
from ultralytics import YOLO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirm import FAULTS, AlertConfirmer  # noqa: E402
from jpeg_like_stream import find_ffmpeg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the colours of the dataset previews (tools/make_ground_dataset.py), as BGR
COL = {"post": (240, 240, 240), "wire": (0, 200, 255), "wire_break": (40, 40, 255), "fallen_post": (255, 0, 255),
       "branch": (120, 255, 0), "cow": (255, 180, 0), "sheep": (255, 120, 0)}
M_PER_DEG = 111132.0


def read_srt(path):
    """DJI subtitles: per block (start time s, latitude, longitude, height above take-off m), sorted by time."""
    stamp = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->")
    field = re.compile(r"([A-Za-z_]+)\s*:\s*(-?\d+(?:\.\d+)?)")
    rows = []
    for block in re.split(r"\n\s*\n", open(path, encoding="utf-8", errors="replace").read()):
        m = stamp.search(block)
        if not m:
            continue
        t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 10 ** len(m[4])
        f = {k.lower(): float(v) for k, v in field.findall(block[m.end():])}
        lat, lon = f.get("latitude"), f.get("longitude", f.get("longtitude"))   # some DJI firmware spells it so
        if lat is None or lon is None or (abs(lat) < 1e-6 and abs(lon) < 1e-6):   # 0,0: no fix yet
            lat = lon = None
        rows.append((t, lat, lon, f.get("rel_alt", f.get("altitude"))))
    return sorted(rows)


class Track:
    """Position at a video time from the SRT, with the course over ground across +-1 s."""

    def __init__(self, rows):
        self.rows = [r for r in rows if r[1] is not None]
        self.t = [r[0] for r in self.rows]
        lat0 = self.rows[0][1] if self.rows else 0.0
        self.kx = M_PER_DEG * math.cos(math.radians(lat0))

    def _at(self, t):
        i = bisect.bisect_left(self.t, t)
        if i == len(self.t) or (i > 0 and t - self.t[i - 1] < self.t[i] - t):
            i -= 1
        return self.rows[i]

    def at(self, t):
        """(lat, lon, alt_m, course_deg or None, speed m/s or None), or None without a fix near t."""
        if not self.rows:
            return None
        r = self._at(t)
        if abs(r[0] - t) > 1.0:
            return None
        a, b = self._at(t - 1.0), self._at(t + 1.0)
        de, dn = (b[2] - a[2]) * self.kx, (b[1] - a[1]) * M_PER_DEG
        d, dt = math.hypot(de, dn), b[0] - a[0]
        course = math.degrees(math.atan2(de, dn)) % 360 if d >= 1.0 else None
        return r[1], r[2], r[3], course, (d / dt if dt > 0 else None)


class FrameConfirmer:
    """Without positions: the same fault class at conf >= conf in n of the last m frames raises an alert; sightings
    of that class within `merge` frames of the alert's last one update it instead of raising another."""

    def __init__(self, n=5, m=8, conf=0.7, merge=45):
        self.n, self.conf, self.merge = n, conf, merge
        self.window = collections.deque(maxlen=m)
        self.alerts, self.active = [], {}

    def update(self, dets, meta):
        seen = {}
        for d in dets:
            if d["class"] in FAULTS and d["conf"] >= self.conf:
                seen[d["class"]] = max(seen.get(d["class"], 0.0), d["conf"])
        self.window.append(seen)
        new = []
        for c, cf in seen.items():
            run = self.active.get(c)
            if run and meta["frame"] - run["last_frame"] <= self.merge:
                run.update(last_frame=meta["frame"], sightings=run["sightings"] + 1,
                           max_conf=max(run["max_conf"], round(cf, 3)))
                continue
            hits = [f[c] for f in self.window if c in f]
            if len(hits) >= self.n:
                run = {"class": c, **meta, "frames": len(hits), "max_conf": round(max(hits), 3),
                       "sightings": len(hits), "last_frame": meta["frame"]}
                self.active[c] = run
                self.alerts.append(run)
                new.append(run)
        return new


def probe(ffmpeg, video):
    """Width, height and duration (s) of the video's first video stream."""
    ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
    ffprobe = ffprobe if os.access(ffprobe, os.X_OK) else shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe not found next to %s" % ffmpeg)
    out = json.loads(subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                     "stream=width,height:format=duration", "-of", "json", video],
                                    capture_output=True, text=True, check=True).stdout)
    s = out["streams"][0]
    return int(s["width"]), int(s["height"]), float(out["format"]["duration"])


def draw(img, dets, alert_conf, hud, banner, scale):
    th = max(1, round(scale))
    for d in dets:
        x0, y0, x1, y1 = (int(v) for v in d["box_xyxy"])
        c, col = d["class"], COL.get(d["class"], (200, 200, 200))
        counts = c in FAULTS and d["conf"] >= alert_conf
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 3 * th if counts else th)
        if c in FAULTS:
            label = "%s %.2f" % (c, d["conf"])
            cv2.putText(img, label, (x0, max(int(14 * scale), y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, col, th)
    for i, (text, bg) in enumerate(((hud, (30, 30, 30)), (banner, (0, 0, 200)))):
        if not text:
            continue
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale, th)
        y = int(8 * scale) + i * (h + int(14 * scale))
        cv2.rectangle(img, (int(6 * scale), y), (int(6 * scale) + w + int(10 * scale), y + h + int(10 * scale)), bg, -1)
        cv2.putText(img, text, (int(11 * scale), y + h + int(4 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale,
                    (255, 255, 255), th)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", default=os.path.expanduser("~/querra-data/models/fence-yolo11n-v0.5.pt"))
    ap.add_argument("--out", help="output folder (default run/video/<video name>)")
    ap.add_argument("--srt", help="DJI subtitle file (default: VIDEO.SRT next to the video, if there is one)")
    ap.add_argument("--no-srt", action="store_true", help="ignore the subtitles: confirm by frames only")
    ap.add_argument("--fps", type=float, default=15.0, help="frames per second to run the detector on")
    ap.add_argument("--width", type=int, default=1280, help="decode width; the height keeps the aspect ratio")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--start", type=float, default=0.0, help="start at this second of the video")
    ap.add_argument("--end", type=float, help="stop at this second")
    ap.add_argument("--det-conf", type=float, default=0.35, help="the detector's threshold (as on the Jetson)")
    ap.add_argument("--conf", type=float, default=0.7, help="a sighting counts toward an alert from this confidence")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--m", type=int, default=8)
    ap.add_argument("--radius", type=float, default=5.0, help="with the SRT: sightings within this many metres")
    ap.add_argument("--merge", type=float, default=10.0, help="with the SRT: one alert per spot within this many m")
    ap.add_argument("--merge-s", type=float, default=3.0, help="without the SRT: one alert per class within this many s")
    ap.add_argument("--pitch", type=float, default=55.0, help="gimbal pitch, degrees below the horizon")
    ap.add_argument("--hfov", type=float, default=69.7, help="horizontal field of view of the video, degrees")
    ap.add_argument("--min-alt", type=float, default=3.0, help="with the SRT: lower frames do not count")
    ap.add_argument("--no-video", action="store_true", help="skip annotated.mp4")
    a = ap.parse_args()

    ffmpeg = find_ffmpeg()
    vw, vh, duration = probe(ffmpeg, a.video)
    W = a.width
    H = int(round(W * vh / vw / 2)) * 2
    end = min(a.end, duration) if a.end else duration
    total = max(0, int((end - a.start) * a.fps))
    out = a.out or os.path.join(ROOT, "run", "video", os.path.splitext(os.path.basename(a.video))[0])
    os.makedirs(os.path.join(out, "alerts"), exist_ok=True)

    srt = None if a.no_srt else a.srt
    if not a.no_srt and not srt:
        srt = next((os.path.splitext(a.video)[0] + e for e in (".SRT", ".srt")
                    if os.path.exists(os.path.splitext(a.video)[0] + e)), None)
    track = Track(read_srt(srt)) if srt else None
    if track is not None and not track.rows:
        print("%s has no GPS fix: confirming by frames only" % srt)
        track = None
    fx = (W / 2.0) / math.tan(math.radians(a.hfov) / 2.0)
    cam = {"img_w": W, "img_h": H, "fx": fx, "pitch_deg": a.pitch}
    if track:
        confirmer = AlertConfirmer(a.n, a.m, a.radius, a.conf, merge_m=a.merge, cam=cam)
        rule = "%d of %d frames within %.0f m on the ground, conf %.2f" % (a.n, a.m, a.radius, a.conf)
    else:
        confirmer = FrameConfirmer(a.n, a.m, a.conf, merge=int(round(a.merge_s * a.fps)))
        rule = "%d of %d consecutive frames, conf %.2f" % (a.n, a.m, a.conf)
    print("%s: %dx%d, %.0f s; detector on %.1f s at %g fps, %dx%d (%d frames); %s; alerts: %s" % (
        os.path.basename(a.video), vw, vh, duration, end - a.start, a.fps, W, H, total,
        "positions from " + os.path.basename(srt) if track else "no positions", rule), flush=True)

    dec = subprocess.Popen([ffmpeg, "-v", "error", "-ss", "%.3f" % a.start, "-i", a.video, "-t", "%.3f" % (end - a.start),
                            "-vf", "fps=%g,scale=%d:%d:flags=area" % (a.fps, W, H), "-an",
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    enc = None if a.no_video else subprocess.Popen(
        [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (W, H), "-r", "%g" % a.fps,
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", os.path.join(out, "annotated.mp4")], stdin=subprocess.PIPE)
    model = YOLO(a.model)
    names = model.names
    log = open(os.path.join(out, "detections.jsonl"), "w")
    scale = W / 1280.0
    banner, banner_until = "", -1.0
    k, t_wall, t_print = 0, time.time(), time.time()
    fsize = W * H * 3
    done = False
    while not done:
        batch = []
        while len(batch) < 8:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                done = True
                break
            batch.append(np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy())
        if not batch:
            break
        results = model.predict(batch, conf=a.det_conf, imgsz=a.imgsz, verbose=False, device="cpu")
        for img, res in zip(batch, results):
            t = a.start + k / a.fps
            dets = [{"class": names[int(c)], "conf": round(float(s), 3), "box_xyxy": [round(float(v), 1) for v in b]}
                    for b, c, s in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist())]
            row = {"frame": k, "t": round(t, 3), "detections": dets}
            meta = {"t": round(t, 2), "frame": k}
            if track:
                pos = track.at(t)
                lat, lon, alt, course, speed = pos if pos else (None, None, None, None, None)
                counts = lat is not None and alt is not None and alt >= a.min_alt
                new = confirmer.update(dets if counts else [], lat, lon, alt, course, meta)
                row.update(lat=lat, lon=lon, alt_m=alt, course_deg=None if course is None else round(course, 1),
                           counts=counts)
                hud = "%6.1f s   %s   alerts %d" % (t, "%.6f, %.6f  %.0f m  %s" % (
                    lat, lon, alt or 0, "%.1f m/s" % speed if speed is not None else "") if lat is not None
                    else "no GPS fix", len(confirmer.alerts))
            else:
                new = confirmer.update(dets, meta)
                hud = "%6.1f s   alerts %d" % (t, len(confirmer.alerts))
            for al in new:
                al["id"] = len(confirmer.alerts) - len(new) + new.index(al) + 1
                if "lat" in al:
                    al["map"] = "https://maps.google.com/?q=%.7f,%.7f" % (al["lat"], al["lon"])
                banner, banner_until = "ALERT %d: %s, conf %.2f" % (al["id"], al["class"], al["max_conf"]), t + 2.0
                print("  ALERT %d at %.1f s: %s, conf %.2f%s" % (al["id"], t, al["class"], al["max_conf"],
                      ", at %.6f, %.6f" % (al["lat"], al["lon"]) if "lat" in al else ""), flush=True)
            log.write(json.dumps(row) + "\n")
            if enc or new:
                draw(img, dets, a.conf, hud, banner if t <= banner_until else "", scale)
            for al in new:
                cv2.imwrite(os.path.join(out, "alerts", "A%02d_%s_%07.1fs.jpg" % (al["id"], al["class"], t)), img,
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
            if enc:
                enc.stdin.write(img.tobytes())
            k += 1
        if time.time() - t_print > 30:
            t_print = time.time()
            print("  frame %d of %d, %.1f fps" % (k, total, k / (time.time() - t_wall)), flush=True)
    dec.wait()
    if enc:
        enc.stdin.close()
        enc.wait()
    log.close()

    order = ("id", "class", "t", "frame", "max_conf", "frames", "sightings", "lat", "lon", "map")
    alerts = [{key: al[key] for key in order if key in al} for al in confirmer.alerts]
    summary = {"video": os.path.abspath(a.video), "srt": os.path.abspath(srt) if track else None,
               "model": os.path.abspath(a.model), "fps": a.fps, "size": [W, H], "start_s": a.start, "end_s": round(end, 2),
               "frames": k, "confirm": rule, "det_conf": a.det_conf, "pitch_deg": a.pitch, "hfov_deg": a.hfov,
               "alerts_by_class": dict(collections.Counter(al["class"] for al in alerts)), "alerts": alerts}
    json.dump(summary, open(os.path.join(out, "alerts.json"), "w"), indent=1)
    print("%d frames in %.0f s; %d alert(s) %s -> %s" % (k, time.time() - t_wall, len(alerts),
                                                        summary["alerts_by_class"] or "", out))


if __name__ == "__main__":
    main()
