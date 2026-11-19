"""Draws YOLO labels on dataset images for spot checks: draw_labels.py <dataset> <split> <out_dir> [n] [glob]"""
import glob, os, random, sys
import cv2
CLASSES = ["post", "wire", "wire_break", "fallen_post", "branch", "cow", "sheep"]
COL = [(40, 120, 255), (0, 220, 255), (0, 0, 255), (255, 0, 255), (0, 120, 0), (255, 255, 255), (255, 200, 0)]
ds, split, out = sys.argv[1:4]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 6
pat = sys.argv[5] if len(sys.argv) > 5 else "*"
os.makedirs(out, exist_ok=True)
imgs = sorted(glob.glob(os.path.join(ds, "images", split, pat + ".png")))
random.Random(1).shuffle(imgs)
for p in imgs[:n]:
    im = cv2.imread(p)
    h, w = im.shape[:2]
    for line in open(p.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"):
        c, cx, cy, bw, bh = line.split()
        c = int(c); cx, cy, bw, bh = float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
        x0, y0, x1, y1 = int(cx - bw / 2), int(cy - bh / 2), int(cx + bw / 2), int(cy + bh / 2)
        cv2.rectangle(im, (x0, y0), (x1, y1), COL[c], 1)
        cv2.putText(im, CLASSES[c], (x0, max(10, y0 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COL[c], 1)
    cv2.imwrite(os.path.join(out, os.path.basename(p).replace(".png", "_labels.jpg")), im, [cv2.IMWRITE_JPEG_QUALITY, 90])
print("wrote", min(n, len(imgs)), "to", out)
