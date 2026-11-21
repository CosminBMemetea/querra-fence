"""Makes a copy of a dataset split whose images look like the live camera stream: MJPEG with 4:2:0 colour, as
tools/cam_stream.py sends them to the Jetson (ffmpeg -c:v mjpeg -q:v 4 -pix_fmt yuvj420p).

    python tools/jpeg_like_stream.py SRC_DIR SPLIT OUT_DIR [--quality 2,3,4,5,6,8] [--share 0.75] [--seed 0] [--prefix L92]

Why: the detectors were trained on lossless PNG renders. Compressed like the stream, the same flight frames raise
false broken-wire alerts as often as the real recorded flight (ml/runs/model-v0.5): the thin wires break up into
JPEG blocks. A share of the frames (--share) is compressed at a random quality from --quality; the rest stay PNG
(hard links, no extra space). Labels are copied. The result is an ordinary YOLO dataset folder.
"""
import argparse
import glob
import os
import random
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor


def find_ffmpeg():
    for p in (os.environ.get("FFMPEG"), os.path.expanduser("~/PX4-Autopilot/Tools/setup/macos/.pixi/envs/default/bin/ffmpeg"),
              shutil.which("ffmpeg")):
        if p and os.access(p, os.X_OK):
            return p
    raise SystemExit("ffmpeg not found: set FFMPEG")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("split"); ap.add_argument("out")
    ap.add_argument("--quality", default="2,3,4,5,6,8", help="ffmpeg -q:v values to draw from (the stream uses 4)")
    ap.add_argument("--share", type=float, default=0.75, help="share of the frames to compress (1: all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prefix", default="", help="only images whose name starts with this, e.g. L92")
    a = ap.parse_args()
    ff, qs = find_ffmpeg(), [int(q) for q in a.quality.split(",")]
    src, out = os.path.expanduser(a.src), os.path.expanduser(a.out)
    imgs = sorted(glob.glob(os.path.join(src, "images", a.split, a.prefix + "*.png")))
    if not imgs:
        raise SystemExit("no images in %s/images/%s" % (src, a.split))
    for d in ("images", "labels"):
        os.makedirs(os.path.join(out, d, a.split), exist_ok=True)
    rnd = random.Random(a.seed)
    jobs = [(p, rnd.random() < a.share, rnd.choice(qs)) for p in imgs]

    def one(job):
        p, compress, q = job
        name = os.path.basename(p)[:-4]
        lab = p.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)[:-4] + ".txt"
        shutil.copyfile(lab, os.path.join(out, "labels", a.split, name + ".txt"))
        if not compress:
            dst = os.path.join(out, "images", a.split, name + ".png")
            if not os.path.exists(dst):
                os.link(p, dst)
            return 0
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", p, "-c:v", "mjpeg", "-q:v", str(q),
                        "-pix_fmt", "yuvj420p", os.path.join(out, "images", a.split, name + ".jpg")], check=True)
        return 1

    with ThreadPoolExecutor(6) as ex:
        n = sum(ex.map(one, jobs))
    print("%s/%s: %d images, %d as stream-like JPEG (q:v %s), %d kept as PNG -> %s" % (
        a.src, a.split, len(imgs), n, a.quality, len(imgs) - n, out))


if __name__ == "__main__":
    main()
