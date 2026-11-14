"""Builds docs/media/* from the raw material recorded by tools/capture_demo.py.

Runs with the PX4 venv Python (Pillow + numpy). Detection boxes are drawn by projecting
the ground-truth Gazebo poses into the inspection camera, the same information the
simulated detector uses; a real deployment would get them from a vision model.
"""
import glob
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim"))
import geo  # noqa: E402

MEDIA = os.path.join(geo.ROOT, "docs", "media")
RAW = os.path.join(MEDIA, "raw")
W, H, HFOV = 640, 400, 1.204
F = (W / 2) / math.tan(HFOV / 2)
CAM_T, CAM_PITCH = (0.13, 0.0, -0.06), 0.96

ORANGE, RED, GREEN, YELLOW = (255, 160, 40), (255, 80, 70), (90, 220, 140), (242, 194, 48)
FAULT_EN = {"wire_break": "broken top wire", "post_down": "fallen post", "branch_short": "branch on wires"}


def font(size, bold=False):
    for path in ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size, index=1 if bold and path.endswith(".ttc") else 0)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def quat_rot(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def camera_from(pose):
    P = np.array(pose[:3])
    Rd = quat_rot(pose[3:])
    c, s = math.cos(CAM_PITCH), math.sin(CAM_PITCH)
    Ry = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return P + Rd @ np.array(CAM_T), Rd @ Ry


def project(C, R, pts):
    out = []
    for X in pts:
        p = R.T @ (np.array(X) - C)
        if p[0] < 0.5:
            return None
        out.append((W / 2 - F * p[1] / p[0], H / 2 - F * p[2] / p[0]))
    return out


def bbox(C, R, pts, min_px=6):
    uv = project(C, R, pts)
    if not uv:
        return None
    us, vs = [u for u, _ in uv], [v for _, v in uv]
    x0, x1, y0, y1 = max(0, min(us)), min(W - 1, max(us)), max(0, min(vs)), min(H - 1, max(vs))
    if x1 - x0 < min_px or y1 - y0 < min_px:
        return None
    return x0, y0, x1, y1


def box_pts(cx, cy, yaw, hl, hw, h):
    c, s = math.cos(yaw), math.sin(yaw)
    pts = []
    for dx in (-hl, hl):
        for dy in (-hw, hw):
            for z in (0.0, h):
                pts.append((cx + c * dx - s * dy, cy + s * dx + c * dy, z))
    return pts


def fault_pts(fence, ft):
    if ft["type"] == "post_down":
        p = fence.posts[ft["post"]]
        return box_pts(p["x"], p["y"], 0, 1.2, 1.2, 1.3)
    k = ft["segment"]
    a, b = fence.posts[k], fence.posts[k + 1]
    pts = [(a["x"], a["y"], 0), (a["x"], a["y"], 1.2), (b["x"], b["y"], 0), (b["x"], b["y"], 1.2)]
    if ft["type"] == "branch_short":
        ox, oy = fence.fault_out(ft)
        mx, my, _ = fence.segment_mid(k)
        pts += [(mx + ox * 3.5, my + oy * 3.5, 3.2), (mx - ox * 2.2, my - oy * 2.2, 0)]
    return pts


def targets(cfg, fence, poses, C, R):
    found = []
    for ft in cfg["faults"]:
        bb = bbox(C, R, fault_pts(fence, ft))
        if bb:
            found.append(dict(kind="fault", id=ft["id"], box=bb, label="FAULT %s · %s" % (ft["id"], FAULT_EN[ft["type"]]), color=ORANGE))
    for name, p in poses.items():
        if not (name[:1] in "VO" and name[1:].isdigit()):
            continue
        cow = name[0] == "V"
        yaw = 2 * math.atan2(p[6], p[3])
        bb = bbox(C, R, box_pts(p[0], p[1], yaw, 1.25 if cow else 0.72, 0.45 if cow else 0.38, 1.6 if cow else 1.05))
        if not bb:
            continue
        out = not geo.inside(fence.poly, p[0], p[1])
        sp = "cow" if cow else "sheep"
        found.append(dict(kind="animal", id=name, box=bb, outside=out, color=RED if out else GREEN,
                          label=("ESCAPED · %s %s" % (sp, name)) if out else "%s %s" % (sp, name)))
    return found


def annotate(img, found, caption, scale=2):
    im = Image.fromarray(img).resize((W * scale, H * scale), Image.LANCZOS)
    d = ImageDraw.Draw(im, "RGBA")
    f = font(11 * scale)
    for t in sorted(found, key=lambda t: t["kind"] == "fault"):
        x0, y0, x1, y1 = [v * scale for v in t["box"]]
        strong = t["kind"] == "fault" or t.get("outside")
        d.rectangle((x0, y0, x1, y1), outline=t["color"] + (255,), width=(3 if strong else 2) * scale // 2 + 1)
        if strong or (x1 - x0) > 30 * scale:
            tw = d.textlength(t["label"], font=f)
            ty = y0 - 15 * scale if y0 > 16 * scale else y1 + 2
            d.rectangle((x0, ty, x0 + tw + 8 * scale, ty + 14 * scale), fill=t["color"] + (230,))
            d.text((x0 + 4 * scale, ty + 1 * scale), t["label"], fill=(15, 15, 15), font=f)
    bar = 22 * scale
    d.rectangle((0, im.height - bar, im.width, im.height), fill=(8, 16, 18, 200))
    d.text((8 * scale, im.height - bar + 5 * scale), caption, fill=(230, 239, 233), font=font(11 * scale))
    d.ellipse((im.width - 16 * scale, im.height - bar + 7 * scale, im.width - 8 * scale, im.height - bar + 15 * scale), fill=(255, 80, 70, 255))
    return im


def latest_png(name):
    files = sorted(glob.glob(os.path.join(RAW, "gui", name, "*.png")))
    return files


def save_jpg(src, dst, width=1600):
    im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst, "JPEG", quality=86, optimize=True, progressive=True)
    return dst


def save_gif(frames, dst, width, fps):
    ims = []
    for fr in frames:
        im = fr if isinstance(fr, Image.Image) else Image.open(fr).convert("RGB")
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        ims.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
    if ims:
        ims[0].save(dst, save_all=True, append_images=ims[1:], duration=int(1000 / fps), loop=0, optimize=True, disposal=1)
    return dst


def report_shot(out):
    reports = sorted(glob.glob(os.path.join(geo.ROOT, "reports", "raport_*.html")))
    brave = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    exe = next((b for b in (chrome, brave) if os.path.exists(b)), None)
    if not reports or not exe:
        return None
    tmp = os.path.join(RAW, "report_full.png")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=860,1900", "--screenshot=" + tmp, "file://" + reports[-1]],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
    if not os.path.exists(tmp):
        return None
    im = Image.open(tmp).convert("RGB")
    a = np.asarray(im).astype(int)
    bg = a[-1, -1]
    rows = np.where(np.abs(a - bg).sum(axis=2).max(axis=1) > 30)[0]
    if len(rows):
        im = im.crop((0, 0, im.width, min(im.height, rows[-1] + 40)))
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    im.save(out, "PNG", optimize=True)
    return out


def main():
    cfg = geo.load_config()
    fence = geo.Fence(cfg)
    os.makedirs(MEDIA, exist_ok=True)
    made = []

    stills = {"01_pasture": "pasture.jpg", "02_drone_on_pad": "x500-on-pad.jpg", "03_fence_energizer": "fence-energizer.jpg",
              "06_result_overview": "result-overview.jpg"}
    for raw, name in stills.items():
        files = latest_png(raw)
        if files:  # the first file is the intended still (later ones can be stray burst frames)
            made.append(save_jpg(files[0], os.path.join(MEDIA, name)))
    flight = latest_png("05_flight")
    for i, fpath in enumerate(flight):
        made.append(save_jpg(fpath, os.path.join(MEDIA, "flight-%d.jpg" % (i + 1)), 1400))
    take = latest_png("04_takeoff")
    if len(take) > 3:
        made.append(save_gif(take, os.path.join(MEDIA, "takeoff.gif"), 720, max(4, len(take) / 9.0)))

    # fault close-ups side by side
    panels = []
    for ft in cfg["faults"]:
        files = latest_png("07_fault_%s" % ft["id"])
        if files:
            im = Image.open(files[0]).convert("RGB")
            im = im.resize((640, round(im.height * 640 / im.width)), Image.LANCZOS)
            d = ImageDraw.Draw(im, "RGBA")
            label = "%s · %s" % (ft["id"], FAULT_EN[ft["type"]])
            d.rectangle((0, im.height - 40, im.width, im.height), fill=(8, 16, 18, 210))
            d.text((14, im.height - 32), label, fill=YELLOW, font=font(20, True))
            panels.append(im)
    if panels:
        h = min(p.height for p in panels)
        strip = Image.new("RGB", (sum(p.width for p in panels) + 8 * (len(panels) - 1), h), (11, 21, 23))
        x = 0
        for p in panels:
            strip.paste(p.crop((0, 0, p.width, h)), (x, 0))
            x += p.width + 8
        strip.save(os.path.join(MEDIA, "faults.jpg"), "JPEG", quality=86, optimize=True)
        made.append(os.path.join(MEDIA, "faults.jpg"))

    # inspection camera: best frame per detection + an annotated GIF of the first detection window
    meta_path = os.path.join(RAW, "stream", "frames.jsonl")
    if os.path.exists(meta_path):
        frames = [json.loads(line) for line in open(meta_path)]
        events = [json.loads(line) for line in open(os.path.join(geo.RUN_DIR, "events.jsonl"))] if os.path.exists(os.path.join(geo.RUN_DIR, "events.jsonl")) else []
        per_frame = []
        for fr in frames:
            pose = fr["poses"].get("x500_fence")
            if not pose:
                per_frame.append(None)
                continue
            C, R = camera_from(pose)
            agl = pose[2]
            per_frame.append((C, R, targets(cfg, fence, fr["poses"], C, R), agl))
        best = {}
        for fr, pf in zip(frames, per_frame):
            if not pf:
                continue
            for t in pf[2]:
                if t["kind"] == "fault" or t.get("outside"):
                    x0, y0, x1, y1 = t["box"]
                    score = -math.hypot((x0 + x1) / 2 - W / 2, (y0 + y1) / 2 - H * 0.55) + 0.02 * (x1 - x0) * (y1 - y0) ** 0.5
                    if t["id"] not in best or score > best[t["id"]][0]:
                        best[t["id"]] = (score, fr["i"], pf)
        for tid, (_, i, pf) in sorted(best.items()):
            img = np.load(os.path.join(RAW, "stream", "%05d.npy" % i))
            cap = "X500 inspection camera · %.0f m AGL · detections from simulation ground truth" % pf[3]
            out = os.path.join(MEDIA, "dronecam-%s.jpg" % tid)
            annotate(img, pf[2], cap).convert("RGB").save(out, "JPEG", quality=88, optimize=True)
            made.append(out)
        # GIF: the longest contiguous recording window (usually the broken wire + escaped cows)
        runs, cur = [], []
        for fr in frames:
            if cur and fr["t"] - cur[-1]["t"] > 1.0:
                runs.append(cur)
                cur = []
            cur.append(fr)
        if cur:
            runs.append(cur)
        if runs:
            run = max(runs, key=len)
            idx = {fr["i"]: k for k, fr in enumerate(frames)}
            gif_frames = []
            for fr in run:
                pf = per_frame[idx[fr["i"]]]
                if not pf:
                    continue
                img = np.load(os.path.join(RAW, "stream", "%05d.npy" % fr["i"]))
                gif_frames.append(annotate(img, pf[2], "X500 inspection camera · %.0f m AGL" % pf[3], scale=1))
            if gif_frames:
                made.append(save_gif(gif_frames, os.path.join(MEDIA, "dronecam.gif"), 640, 8))
        del events

    rs = report_shot(os.path.join(MEDIA, "report.png"))
    if rs:
        made.append(rs)
    for m in made:
        print("  %-34s %6.0f KB" % (os.path.relpath(m, geo.ROOT), os.path.getsize(m) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
