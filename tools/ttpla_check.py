"""A drone model on TTPLA: real drone photos of power lines (3840x2160, Apache-2.0, github.com/R3ab/ttpla_dataset), with
no farm fence in them. Every fault box is a false alarm, so this counts false faults per frame on real scenes; the
labelled cables and wooden poles show whether the model sees real wires and poles at all (wire, post).

    ~/.querra-train-venv/bin/python tools/ttpla_check.py ~/querra-data/real/ttpla/raw MODEL.pt OUT.json

RAW_DIR holds TTPLA's images and labelme JSON files side by side (data_original_size_v1.zip, unpacked flat)."""
import glob, json, os, sys
import numpy as np
from ultralytics import YOLO

raw, mp, out = sys.argv[1], sys.argv[2], sys.argv[3]
NAMES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]
m = YOLO(mp)
imgs = sorted(glob.glob(os.path.join(raw, "*.jpg")))
res = {"frames": len(imgs), "false": {n: {"0.5": 0, "0.7": 0} for n in ("wire_break", "fallen_post", "branch", "cow", "sheep")},
       "cable_frames": 0, "cable_frames_with_wire_0.5": 0, "cable_points": 0, "cable_points_in_wire_0.5": 0,
       "poles": 0, "poles_with_post_0.5": 0, "examples": {}}


def inside(pts, boxes):
    if not boxes:
        return np.zeros(len(pts), bool)
    b = np.array(boxes)
    return ((pts[:, None, 0] >= b[None, :, 0]) & (pts[:, None, 0] <= b[None, :, 2]) &
            (pts[:, None, 1] >= b[None, :, 1]) & (pts[:, None, 1] <= b[None, :, 3])).any(1)


def dense(poly, step=20):
    p = np.array(poly, float)
    seg = [np.linspace(a, b, max(2, int(np.hypot(*(b - a)) / step))) for a, b in zip(p, np.roll(p, -1, 0))]
    return np.vstack(seg)


for k in range(0, len(imgs), 16):
    batch = imgs[k:k + 16]
    for p, r in zip(batch, m.predict(batch, conf=0.25, imgsz=640, verbose=False, device="cpu")):
        dets = [(NAMES[int(c)], s, b) for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
        for n in res["false"]:
            for th in ("0.5", "0.7"):
                if any(d[0] == n and d[1] >= float(th) for d in dets):
                    res["false"][n][th] += 1
                    if th == "0.7":
                        res["examples"].setdefault(n, []).append(os.path.basename(p))
        shapes = json.load(open(p[:-4] + ".json"))["shapes"]
        wires = [d[2] for d in dets if d[0] == "wire" and d[1] >= 0.5]
        posts = [d[2] for d in dets if d[0] == "post" and d[1] >= 0.5]
        cables = [s for s in shapes if s["label"].lower() == "cable"]
        if cables:
            res["cable_frames"] += 1
            res["cable_frames_with_wire_0.5"] += bool(wires)
            pts = np.vstack([dense(s["points"]) for s in cables])
            res["cable_points"] += len(pts)
            res["cable_points_in_wire_0.5"] += int(inside(pts, wires).sum())
        for s in shapes:
            if s["label"] == "tower_wooden":
                res["poles"] += 1
                c = np.array(s["points"], float)
                centre = np.array([[c[:, 0].mean(), c[:, 1].mean()]])
                res["poles_with_post_0.5"] += bool(inside(centre, posts)[0])
    print("%d/%d" % (min(k + 16, len(imgs)), len(imgs)), flush=True)
for n in res["examples"]:
    res["examples"][n] = res["examples"][n][:10]
json.dump(res, open(out, "w"), indent=1)
f = res["frames"]
print("false faults per frame from 0.7:", {n: "%d (%.1f%%)" % (v["0.7"], 100 * v["0.7"] / f) for n, v in res["false"].items()})
print("false faults per frame from 0.5:", {n: "%d (%.1f%%)" % (v["0.5"], 100 * v["0.5"] / f) for n, v in res["false"].items()})
print("cable frames with a wire box from 0.5: %d of %d; cable length inside wire boxes: %.1f%%" % (
    res["cable_frames_with_wire_0.5"], res["cable_frames"], 100 * res["cable_points_in_wire_0.5"] / max(1, res["cable_points"])))
print("wooden poles with a post box from 0.5: %d of %d" % (res["poles_with_post_0.5"], res["poles"]))
