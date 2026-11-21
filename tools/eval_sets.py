"""Scores fence detector checkpoints on the held-out sets in both world looks, for the retraining log.

    python tools/eval_sets.py MODEL.pt [MODEL.pt ...] [--device cpu] [--sets NAME=SPEC ...] [--json out.json]
    SPEC = dataset_dir:split[:L40,L41]   (as in tools/mix_dataset.py)

Default sets (~/querra-data): the held-out farms, the test seeds 140-142 and the mission pasture in the classic and the
rich look, and the re-fly close-ups (6 m hover) in both looks. None of them is used for training.
Prints one Markdown table per model pair: mAP50 (all), wire_break mAP50 and its precision / recall, and wb_false: the
share of frames with a false broken wire at conf >= 0.7 (no labelled break overlaps it), the measure that predicts
false alerts in flight. Sets may hold .png or stream-like .jpg images (tools/jpeg_like_stream.py).
"""
import argparse
import glob
import json
import os
import tempfile

from ultralytics import YOLO

D = os.path.expanduser("~/querra-data")
CLASSES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]
SETS = [
    ("classic: old validation farms", D + "/fence_yolo:val"),
    ("classic: v2 validation farms", D + "/fence_yolo_v2:val"),
    ("classic: test seeds 140-142", D + "/fence_yolo_v2:test:L40,L41,L42"),
    ("classic: mission pasture", D + "/fence_yolo_v2:test:L90"),
    ("classic: re-fly close-ups", D + "/fence_yolo_refly_classic:test"),
    ("rich: validation farms", D + "/fence_yolo_rich:val"),
    ("rich: test seeds 140-142", D + "/fence_yolo_rich:test:L40,L41,L42"),
    ("rich: mission pasture", D + "/fence_yolo_rich:test:L90"),
    ("rich: re-fly close-ups", D + "/fence_yolo_refly_rich:test"),
]


def set_yaml(spec, tmp):
    parts = spec.split(":")
    root, split = os.path.expanduser(parts[0]), parts[1]
    prefixes = parts[2].split(",") if len(parts) > 2 else [""]
    imgs = sorted(p for pre in prefixes for ext in ("png", "jpg")
                  for p in glob.glob(os.path.join(root, "images", split, pre + "*." + ext)))
    if not imgs:
        return None, 0, []
    lst = os.path.join(tmp, "%d.txt" % abs(hash(spec)))
    with open(lst, "w") as fh:
        fh.write("\n".join(imgs) + "\n")
    y = lst[:-4] + ".yaml"
    with open(y, "w") as fh:
        fh.write("path: %s\ntrain: %s\nval: %s\nnames:\n" % (tmp, lst, lst) + "".join("  %d: %s\n" % (i, c) for i, c in enumerate(CLASSES)))
    return y, len(imgs), imgs


def false_breaks(model, imgs, device, conf=0.7):
    """Percent of frames with a predicted wire_break that overlaps no labelled break (IoU < 0.1)."""
    k = CLASSES.index("wire_break")

    def iou(a, b):
        ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy + 1e-9)
    bad = 0
    for i in range(0, len(imgs), 32):
        for path, r in zip(imgs[i:i + 32], model.predict(imgs[i:i + 32], imgsz=640, conf=conf, device=device, verbose=False)):
            gt = []
            for line in open(os.path.splitext(path.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep))[0] + ".txt"):
                c, x, y, w, h = map(float, line.split())
                if int(c) == k:
                    gt.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
            if any(int(c) == k and all(iou(b, g) < 0.1 for g in gt) for b, c in zip(r.boxes.xyxyn.tolist(), r.boxes.cls.tolist())):
                bad += 1
    return round(100 * bad / len(imgs), 1)


def score(model, y, device):
    m = model.val(data=y, split="val", imgsz=640, batch=16, device=device, plots=False, verbose=False, workers=2)
    b = m.box
    idx = list(b.ap_class_index)
    out = {"all": round(float(b.map50), 3)}
    for c in ("wire_break", "fallen_post", "branch"):
        k = CLASSES.index(c)
        if k in idx:
            j = idx.index(k)
            out[c] = round(float(b.ap50[j]), 3)
            if c == "wire_break":
                out["wb_p"], out["wb_r"] = round(float(b.p[j]), 2), round(float(b.r[j]), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--sets", nargs="*", help="NAME=SPEC, replaces the default sets")
    ap.add_argument("--json")
    args = ap.parse_args()
    sets = [tuple(s.split("=", 1)) for s in args.sets] if args.sets else SETS
    res = {}
    with tempfile.TemporaryDirectory() as tmp:
        for mp in args.models:
            model = YOLO(mp)
            for name, spec in sets:
                y, n, imgs = set_yaml(spec, tmp)
                if y is None:
                    print("skip %s (no images)" % name)
                    continue
                res.setdefault(name, {"n": n})[mp] = dict(score(model, y, args.device), wb_false=false_breaks(model, imgs, args.device))
                print(name, mp, res[name][mp], flush=True)
    names = [os.path.basename(os.path.dirname(os.path.dirname(m))) if m.endswith("best.pt") else os.path.basename(m) for m in args.models]
    print("\n| Set | Frames | mAP50 all | wire_break mAP50 | wire_break P / R | false wire_break frames | fallen_post | branch |")
    print("|---|---|---|---|---|---|---|---|")
    for name, r in res.items():
        cols = [" → ".join(str(r[m].get(k, "-")) for m in args.models if m in r) for k in ("all", "wire_break")]
        pr = " → ".join("%s / %s" % (r[m].get("wb_p", "-"), r[m].get("wb_r", "-")) for m in args.models if m in r)
        fp = " → ".join(str(r[m].get("fallen_post", "-")) for m in args.models if m in r)
        br = " → ".join(str(r[m].get("branch", "-")) for m in args.models if m in r)
        wf = " → ".join("%s%%" % r[m].get("wb_false", "-") for m in args.models if m in r)
        print("| %s | %d | %s | %s | %s | %s | %s | %s |" % (name, r["n"], cols[0], cols[1], pr, wf, fp, br))
    print("\nmodels: " + " → ".join(names))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
