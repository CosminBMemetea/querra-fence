"""Label real fence footage: a model drafts the boxes, you fix them in the browser, then models are scored on them.

  ~/.querra-train-venv/bin/python tools/label_drafts.py draft VIDEO_OR_FOLDER --model MODEL.pt [--every 1] [--out DIR]
  python3 tools/label_drafts.py serve DIR             # http://127.0.0.1:8765 : check every box, fix, Enter saves
  ~/.querra-train-venv/bin/python tools/label_drafts.py score DIR --model A.pt [B.pt ...]

draft   takes one frame every --every seconds of a video (or every image of a folder) into DIR/images/all and writes
        the model's boxes from --conf (0.25) to DIR/drafts. It never touches reviewed labels: run it again on the same
        DIR with another --model to redraw the drafts only. DIR defaults to ~/querra-data/real/<video name>.
serve   a page on 127.0.0.1 to review the frames. The drafts load as editable boxes: delete the wrong ones, fix the
        rest, draw what the model missed, Enter saves. A saved frame's boxes go to DIR/labels/all (YOLO format) and
        the frame to DIR/reviewed.txt; a skipped frame (S: blurred, no fence in view) is left out of the test set.
score   the reviewed frames as a test set (DIR/data.yaml): mAP50 per class, and for each fault class the recall,
        precision and share of frames with a false box at conf 0.5 and 0.7, the thresholds the alerts use. Results
        go to DIR/scores/<model>.json.

The folder is a YOLO dataset (images/all, labels/all, reviewed.txt, data.yaml). Class conventions are in
docs/labelling.md. Drafts lean toward what the drafting model sees, so look for what it missed before saving; a model
scored on labels it drafted keeps a small advantage. Real footage stays out of git (~/querra-data/real).
"""
import argparse
import datetime
import glob
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]
FAULTS = {2: "wire_break", 3: "fallen_post", 4: "branch"}
IMG_EXT = (".jpg", ".jpeg", ".png")
UI = os.environ.get("LABEL_UI", os.path.join(ROOT, "tools", "label_ui.html"))


def paths(d):
    return {"img": os.path.join(d, "images", "all"), "lab": os.path.join(d, "labels", "all"),
            "draft": os.path.join(d, "drafts"), "review": os.path.join(d, "review.json"),
            "list": os.path.join(d, "reviewed.txt"), "meta": os.path.join(d, "meta.json"),
            "yaml": os.path.join(d, "data.yaml")}


def load(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def frames(d):
    """Frame names (file names in images/all), in order."""
    return sorted(n for n in os.listdir(paths(d)["img"]) if n.lower().endswith(IMG_EXT))


def stem(n):
    return os.path.splitext(n)[0]


def read_boxes(p, with_conf=False):
    out = []
    try:
        for line in open(p):
            v = line.split()
            if len(v) >= 5:
                b = [int(v[0])] + [float(x) for x in v[1:5]]
                if with_conf:
                    b.append(float(v[5]) if len(v) > 5 else 1.0)
                out.append(b)
    except OSError:
        return None
    return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_yaml(d):
    P = paths(d)
    with open(P["yaml"], "w") as f:
        f.write("# The reviewed frames of %s as a test set (tools/label_drafts.py score). Not for training as is.\n"
                "path: %s\ntrain: reviewed.txt\nval: reviewed.txt\ntest: reviewed.txt\nnames:\n%s"
                % (os.path.basename(d), d, "".join("  %d: %s\n" % (i, c) for i, c in enumerate(CLASSES))))


def write_list(d, review):
    P = paths(d)
    done = [n for n in frames(d) if review.get(n, {}).get("status") == "done"]
    with open(P["list"], "w") as f:
        f.write("".join(os.path.join(P["img"], n) + "\n" for n in done))
    return len(done)


# ---------------------------------------------------------------- draft

def extract(src, d, a):
    """One frame every a.every seconds: the first frame of each interval, so a frame's time is exact to one video
    frame. The times come from ffmpeg's showinfo."""
    P, name = paths(d), stem(os.path.basename(src))
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from jpeg_like_stream import find_ffmpeg
    ff = find_ffmpeg()
    cmd = [ff, "-hide_banner", "-loglevel", "info", "-nostats", "-ss", str(a.start), "-i", src]
    if a.end:
        cmd += ["-t", str(a.end - a.start)]
    e = "%g" % a.every
    cmd += ["-vf", "select='isnan(prev_selected_t)+gte(floor(t/%s)-floor(prev_selected_t/%s),1)',scale='min(%d,iw)':-2,showinfo"
            % (e, e, a.width), "-fps_mode", "vfr", "-q:v", "2", "-start_number", "0", os.path.join(P["img"], name + "_%05d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("ffmpeg failed:\n" + r.stderr[-2000:])
    shown = [float(t) for t in re.findall(r"Parsed_showinfo.*? n:\s*\d+ .*?pts_time:\s*([-\d.]+)", r.stderr)]
    times = {}
    for n in frames(d):
        i = int(stem(n).rsplit("_", 1)[1])
        times[n] = round(a.start + (shown[i] if i < len(shown) else i * a.every), 2)
    return times


def cmd_draft(a):
    src = os.path.abspath(os.path.expanduser(a.source))
    if not os.path.exists(src):
        raise SystemExit("not found: " + src)
    d = os.path.abspath(os.path.expanduser(a.out or os.path.join("~/querra-data/real", stem(os.path.basename(src.rstrip("/"))))))
    P = paths(d)
    for k in ("img", "lab", "draft"):
        os.makedirs(P[k], exist_ok=True)
    meta = load(P["meta"], {})
    if frames(d):
        print("[label] %s already has %d frames: redrawing the drafts only" % (d, len(frames(d))))
    elif os.path.isdir(src):
        for p in sorted(glob.glob(os.path.join(src, "*"))):
            if p.lower().endswith(IMG_EXT):
                shutil.copy2(p, os.path.join(P["img"], os.path.basename(p).replace(" ", "_")))
        meta.update(source=src, kind="images", times={})
    else:
        meta.update(source=src, kind="video", every_s=a.every, start_s=a.start, end_s=a.end, width=a.width,
                    times=extract(src, d, a))
    names = frames(d)
    if not names:
        raise SystemExit("no frames")
    from ultralytics import YOLO
    m = YOLO(os.path.expanduser(a.model))
    model_names = [m.names[i] for i in range(len(m.names))]
    if model_names != CLASSES:
        print("[label] warning: the model's classes %s are not the fence classes %s" % (model_names, CLASSES))
    for f in glob.glob(os.path.join(P["draft"], "*.txt")):
        os.remove(f)
    n_boxes = 0
    for k in range(0, len(names), 16):
        batch = names[k:k + 16]
        res = m.predict([os.path.join(P["img"], n) for n in batch], conf=a.conf, imgsz=a.imgsz, device=a.device, verbose=False)
        for n, r in zip(batch, res):
            rows = ["%d %.6f %.6f %.6f %.6f %.3f" % (int(c), *b, s)
                    for c, b, s in zip(r.boxes.cls.tolist(), r.boxes.xywhn.tolist(), r.boxes.conf.tolist())]
            n_boxes += len(rows)
            with open(os.path.join(P["draft"], stem(n) + ".txt"), "w") as f:
                f.write("".join(x + "\n" for x in rows))
        print("\r[label] drafts: %d of %d frames" % (min(k + 16, len(names)), len(names)), end="", flush=True)
    print()
    mp = os.path.abspath(os.path.expanduser(a.model))
    meta["drafts"] = {"model": mp.replace(os.path.expanduser("~"), "~"), "sha256": sha256(mp), "conf": a.conf,
                      "imgsz": a.imgsz, "date": datetime.datetime.now().isoformat(timespec="seconds")}
    meta["created"] = meta.get("created", meta["drafts"]["date"])
    save(P["meta"], meta)
    write_yaml(d)
    write_list(d, load(P["review"], {}))
    print("[label] %d frames, %d draft boxes from conf %.2f in %s" % (len(names), n_boxes, a.conf, d))
    print("[label] review them: python3 tools/label_drafts.py serve %s" % d.replace(os.path.expanduser("~"), "~"))


# ---------------------------------------------------------------- serve

class Handler(http.server.BaseHTTPRequestHandler):
    d = None
    port = None
    lock = threading.Lock()

    def log_message(self, fmt, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def local(self):
        """Only this page may talk to the server: the Host must be ours (no DNS rebinding)."""
        return self.headers.get("Host") in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    def frame(self, q):
        n = (q.get("name") or [""])[0]
        return n if n in frames(self.d) else None

    def do_GET(self):
        if not self.local():
            return self.reply(403, {"error": "host"})
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        P = paths(self.d)
        if u.path == "/":
            with open(UI, "rb") as f:
                return self.reply(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            meta, review = load(P["meta"], {}), load(P["review"], {})
            times = meta.get("times", {})
            return self.reply(200, {"name": os.path.basename(self.d), "classes": CLASSES, "drafts": meta.get("drafts"),
                                    "frames": [{"name": n, "t": times.get(n), "status": review.get(n, {}).get("status", "todo")}
                                               for n in frames(self.d)]})
        if u.path == "/api/frame":
            n = self.frame(q)
            if not n:
                return self.reply(404, {"error": "no such frame"})
            st = load(P["review"], {}).get(n, {}).get("status", "todo")
            return self.reply(200, {"name": n, "status": st,
                                    "draft": read_boxes(os.path.join(P["draft"], stem(n) + ".txt"), True) or [],
                                    "label": read_boxes(os.path.join(P["lab"], stem(n) + ".txt")) if st == "done" else None})
        if u.path == "/img":
            n = self.frame(q)
            if not n:
                return self.reply(404, {"error": "no such frame"})
            with open(os.path.join(P["img"], n), "rb") as f:
                return self.reply(200, f.read(), "image/png" if n.lower().endswith(".png") else "image/jpeg")
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        # JSON only: a cross-site page cannot send it without a CORS preflight, which this server never allows
        if not self.local() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(403, {"error": "forbidden"})
        if urllib.parse.urlparse(self.path).path != "/api/save":
            return self.reply(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 1 << 20)))
            n, status = body["name"], body["status"]
            assert n in frames(self.d) and status in ("done", "skip", "todo")
            boxes = []
            for b in body.get("boxes", []):
                c, cx, cy, w, h = int(b[0]), *(float(x) for x in b[1:5])
                assert 0 <= c < len(CLASSES)
                x0, y0, x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2), min(1.0, cx + w / 2), min(1.0, cy + h / 2)
                if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
                    boxes.append((c, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0))
        except (ValueError, KeyError, TypeError, AssertionError, IndexError):
            return self.reply(400, {"error": "bad request"})
        P = paths(self.d)
        with self.lock:
            lab = os.path.join(P["lab"], stem(n) + ".txt")
            if status == "done":
                with open(lab, "w") as f:
                    f.write("".join("%d %.6f %.6f %.6f %.6f\n" % b for b in boxes))
            elif os.path.exists(lab):
                os.remove(lab)
            review = load(P["review"], {})
            if status == "todo":
                review.pop(n, None)
            else:
                review[n] = {"status": status, "boxes": len(boxes) if status == "done" else 0,
                             "saved": datetime.datetime.now().isoformat(timespec="seconds")}
            save(P["review"], review)
            done = write_list(self.d, review)
        self.reply(200, {"ok": True, "done": done})


def cmd_serve(a):
    d = os.path.abspath(os.path.expanduser(a.dir))
    if not os.path.isdir(paths(d)["img"]) or not frames(d):
        raise SystemExit("no frames in %s: run 'draft' first" % d)
    os.makedirs(paths(d)["lab"], exist_ok=True)
    Handler.d, Handler.port = d, a.port
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://127.0.0.1:%d/" % a.port
    print("[label] %d frames in %s\n[label] %s  (Ctrl+C to stop; every save is written at once)" % (len(frames(d)), d, url))
    if not a.no_open:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------- score

def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def xyxy(b):
    return (b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2)


def fault_table(model, imgs, P, a):
    """Per fault class, at each threshold: recall, precision (a box is right at IoU >= 0.3 with a label of its class)
    and the share of frames with a false box of the class."""
    preds = []
    for k in range(0, len(imgs), 16):
        for p, r in zip(imgs[k:k + 16], model.predict(imgs[k:k + 16], conf=0.25, imgsz=a.imgsz, device=a.device, verbose=False)):
            gt = read_boxes(os.path.join(P["lab"], stem(os.path.basename(p)) + ".txt")) or []
            preds.append(([(int(b[0]), xyxy(b[1:])) for b in gt],
                          [(int(c), s, xyxy(b)) for c, s, b in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xywhn.tolist())]))
    out = {}
    for c, name in FAULTS.items():
        n_gt = sum(1 for g, _ in preds for gc, _ in g if gc == c)
        out[name] = {"labelled": n_gt}
        for th in (0.5, 0.7):
            tp = fp = bad_frames = 0
            for g, pr in preds:
                gts = [b for gc, b in g if gc == c]
                used, bad = set(), False
                for _, s, b in sorted((x for x in pr if x[0] == c and x[1] >= th), key=lambda x: -x[1]):
                    j = max(range(len(gts)), key=lambda j: iou(b, gts[j]), default=None)
                    if j is not None and j not in used and iou(b, gts[j]) >= 0.3:
                        used.add(j)
                        tp += 1
                    else:
                        fp += 1
                        bad = True
                bad_frames += bad
            out[name][str(th)] = {"recall": round(tp / n_gt, 3) if n_gt else None,
                                  "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                                  "false_frames_pct": round(100.0 * bad_frames / len(preds), 1)}
    return out


def cmd_score(a):
    d = os.path.abspath(os.path.expanduser(a.dir))
    P = paths(d)
    write_list(d, load(P["review"], {}))
    imgs = [l.strip() for l in open(P["list"]) if l.strip()] if os.path.exists(P["list"]) else []
    if not imgs:
        raise SystemExit("no reviewed frames in %s yet" % d)
    write_yaml(d)
    counts = [0] * len(CLASSES)
    for p in imgs:
        for b in read_boxes(os.path.join(P["lab"], stem(os.path.basename(p)) + ".txt")) or []:
            counts[b[0]] += 1
    print("[label] %d reviewed frames; labels: %s" % (len(imgs), ", ".join("%s %d" % (c, n) for c, n in zip(CLASSES, counts) if n)))
    from ultralytics import YOLO
    os.makedirs(os.path.join(d, "scores"), exist_ok=True)
    rows = []
    for mp in a.model:
        m = YOLO(os.path.expanduser(mp))
        with tempfile.TemporaryDirectory() as tmp:
            r = m.val(data=P["yaml"], split="test", imgsz=a.imgsz, batch=16, device=a.device, workers=0, verbose=False,
                      plots=False, project=tmp, name="val")
        ap = {CLASSES[int(c)]: round(float(v), 3) for c, v in zip(r.box.ap_class_index, r.box.ap50)}
        res = {"model": os.path.abspath(os.path.expanduser(mp)).replace(os.path.expanduser("~"), "~"),
               "sha256": sha256(os.path.expanduser(mp)), "frames": len(imgs), "labels": dict(zip(CLASSES, counts)),
               "mAP50": round(float(r.box.map50), 3), "mAP50-95": round(float(r.box.map), 3),
               "ap50_per_class": ap, "faults": fault_table(m, imgs, P, a),
               "date": datetime.datetime.now().isoformat(timespec="seconds")}
        save(os.path.join(d, "scores", stem(os.path.basename(mp)) + ".json"), res)
        rows.append((stem(os.path.basename(mp)), res))
    f = lambda v: "–" if v is None else "%.2f" % v
    print("\n| Model | mAP50 | " + " | ".join("%s from 0.7: recall / precision / false frames" % n for n in FAULTS.values()) + " |")
    print("|---|---|" + "---|" * len(FAULTS))
    for name, res in rows:
        cells = []
        for n in FAULTS.values():
            t = res["faults"][n]["0.7"]
            cells.append("%s / %s / %.1f%%" % (f(t["recall"]), f(t["precision"]), t["false_frames_pct"]))
        print("| %s | %.3f | %s |" % (name, res["mAP50"], " | ".join(cells)))
    print("\n[label] details in %s/scores/" % d.replace(os.path.expanduser("~"), "~"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft", help="frames from a video or folder, and the model's boxes as drafts")
    p.add_argument("source", help="a video (phone, DJI) or a folder of images")
    p.add_argument("--model", required=True, help="the drafting model (.pt)")
    p.add_argument("--out", help="the dataset folder (default ~/querra-data/real/<name>)")
    p.add_argument("--every", type=float, default=1.0, help="seconds between frames taken from a video")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float)
    p.add_argument("--width", type=int, default=1280, help="largest frame width kept from a video")
    p.add_argument("--conf", type=float, default=0.25, help="draft boxes from this confidence")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="cpu")
    p = sub.add_parser("serve", help="review the drafts in the browser")
    p.add_argument("dir")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    p = sub.add_parser("score", help="score models on the reviewed frames")
    p.add_argument("dir")
    p.add_argument("--model", nargs="+", required=True)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="cpu")
    a = ap.parse_args()
    {"draft": cmd_draft, "serve": cmd_serve, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
