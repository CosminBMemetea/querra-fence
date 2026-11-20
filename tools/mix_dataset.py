"""Writes a training mix of several auto-labelled datasets as image lists (no copies), for tools/train_yolo.py --data.

    python tools/mix_dataset.py OUT_DIR --train SPEC [SPEC ...] --val SPEC [SPEC ...] [--seed 0]
    SPEC = dataset_dir:split[:L20,L21][@N]   (optional layout prefixes; @N keeps N random images)

Example (model-v0.4):
    python tools/mix_dataset.py ~/querra-data/fence_yolo_v4 \\
        --train ~/querra-data/fence_yolo_rich:train ~/querra-data/fence_yolo_v3c:train \\
                ~/querra-data/fence_yolo_v2:train ~/querra-data/fence_yolo:train@1800 \\
        --val ~/querra-data/fence_yolo_rich:val ~/querra-data/fence_yolo_v2:val ~/querra-data/fence_yolo:val
Labels are found the YOLO way (/images/ -> /labels/, .png -> .txt).
"""
import argparse
import glob
import os
import random

CLASSES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]


def images(spec, rnd):
    spec, _, n = spec.partition("@")
    parts = spec.split(":")
    root, split = os.path.expanduser(parts[0]), parts[1]
    prefixes = parts[2].split(",") if len(parts) > 2 else [""]
    out = sorted(p for pre in prefixes for p in glob.glob(os.path.join(root, "images", split, pre + "*.png")))
    if not out:
        raise SystemExit("no images for %s" % spec)
    if n:
        out = sorted(rnd.sample(out, min(int(n), len(out))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--train", nargs="+", required=True)
    ap.add_argument("--val", nargs="+", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)
    for name, specs in (("train", args.train), ("val", args.val)):
        lst = []
        for s in specs:
            got = images(s, rnd)
            print("%-5s %-60s %5d images" % (name, s, len(got)))
            lst += got
        with open(os.path.join(out, name + ".txt"), "w") as fh:
            fh.write("\n".join(lst) + "\n")
        print("%-5s total %d" % (name, len(lst)))
    with open(os.path.join(out, "data.yaml"), "w") as fh:
        fh.write("path: %s\ntrain: train.txt\nval: val.txt\nnames:\n" % out +
                 "".join("  %d: %s\n" % (i, c) for i, c in enumerate(CLASSES)))
        fh.write("# mix: --train %s --val %s --seed %d\n" % (" ".join(args.train), " ".join(args.val), args.seed))
    print("wrote", os.path.join(out, "data.yaml"))


if __name__ == "__main__":
    main()
