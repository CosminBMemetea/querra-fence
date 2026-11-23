"""Score a fence detector on the ground robot's patrol: faults found and false alerts, as the alert chain would count them.

  ~/.querra-train-venv/bin/python tools/ground_patrol_eval.py MODEL.pt [--frames DIR] [--conf 0.5] [--json OUT]

The frames are the real forest.json world along the robot's patrol route, one every 0.5 m, from the robot's side
camera (tools/make_ground_dataset.sh --patrol; patrol_poses.jsonl and patrol_faults.json sit next to them), usually
compressed like the camera stream (tools/jpeg_like_stream.py --quality 4 --share 1). The model never saw this world.

An alert needs the same fault class in 5 of 8 consecutive frames, like the Jetson's alert_confirm (there: 5 of 8
within 5 m on the ground; here the frames are 0.5 m apart, so 8 frames span 4 m of route). Alerts of one class
closer than 5 m along the route merge into one. An alert is a find when a fault of its class lies within 4 m of
the robot's position while it was raised; otherwise it is a false alert. The phase 0 goal: at least 4 of 5 faults
found and at most 1 false alert per patrol.
"""
import argparse
import json
import math
import os

from ultralytics import YOLO

FAULT_CLASSES = {2: "wire_break", 3: "fallen_post", 4: "branch"}
TYPE_CLASS = {"wire_break": 2, "post_down": 3, "branch_short": 4}

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("model")
ap.add_argument("--frames", default=os.path.expanduser("~/querra-data/ground_patrol_q4/images/test"))
ap.add_argument("--meta", default=os.path.expanduser("~/querra-data/ground_patrol"),
                help="folder with patrol_poses.jsonl and patrol_faults.json")
ap.add_argument("--conf", type=float, default=0.5)
ap.add_argument("--window", type=int, default=8)
ap.add_argument("--need", type=int, default=5)
ap.add_argument("--json", help="write the result here")
a = ap.parse_args()

poses = [json.loads(line) for line in open(os.path.join(a.meta, "patrol_poses.jsonl"))]
faults = json.load(open(os.path.join(a.meta, "patrol_faults.json")))["faults"]
names = sorted(os.listdir(a.frames))
by_stem = {os.path.splitext(n)[0]: n for n in names}
frames = [(p, os.path.join(a.frames, by_stem[p["name"]])) for p in poses if p["name"] in by_stem]
model = YOLO(a.model)
hits = []                                   # per frame: {class: best confidence}
for k in range(0, len(frames), 32):
    batch = frames[k:k + 32]
    for res in model.predict([f for _, f in batch], conf=a.conf, verbose=False, device="cpu"):
        best = {}
        for c, s in zip(res.boxes.cls.tolist(), res.boxes.conf.tolist()):
            c = int(c)
            if c in FAULT_CLASSES:
                best[c] = max(best.get(c, 0.0), s)
        hits.append(best)

alerts = []
for c in FAULT_CLASSES:
    run = None
    for i in range(len(hits)):
        win = hits[max(0, i - a.window + 1):i + 1]
        if sum(1 for h in win if c in h) >= a.need:
            if run and i - run["last"] <= 10:       # within 5 m (10 frames) of the last one: the same alert
                run["last"] = i
            else:
                run = {"cls": c, "first": i, "last": i}
                alerts.append(run)
result = {"model": os.path.abspath(a.model), "frames": len(frames), "conf": a.conf,
          "confirm": "%d of %d frames" % (a.need, a.window), "faults": [], "false_alerts": []}
found = set()
for al in alerts:
    ps = [frames[i][0] for i in range(al["first"], al["last"] + 1)]
    match = None
    for ft in faults:
        if TYPE_CLASS[ft["type"]] == al["cls"] and min(math.hypot(p["x"] - ft["x"], p["y"] - ft["y"]) for p in ps) <= 4.0:
            match = ft
    al.update(cls=FAULT_CLASSES[al["cls"]], x=round(ps[0]["x"], 1), y=round(ps[0]["y"], 1),
              conf=round(max(hits[i].get(TYPE_CLASS.get(match["type"]) if match else 0, 0) or
                             max(hits[i].values(), default=0) for i in range(al["first"], al["last"] + 1)), 2))
    if match:
        found.add(match["id"])
        al["fault"] = match["id"]
    else:
        result["false_alerts"].append(al)
for ft in faults:
    c = TYPE_CLASS[ft["type"]]
    near = [i for i, (p, _) in enumerate(frames) if math.hypot(p["x"] - ft["x"], p["y"] - ft["y"]) <= 4.0]
    frames_seen = sum(1 for i in near if c in hits[i])
    result["faults"].append({"id": ft["id"], "type": ft["type"], "found": ft["id"] in found,
                             "frames_with_its_class": frames_seen, "frames_in_view": len(near)})
result["found"] = len(found)
result["false_alert_count"] = len(result["false_alerts"])
result["frames_with_false_class"] = {FAULT_CLASSES[c]: sum(
    1 for i, (p, _) in enumerate(frames) if c in hits[i] and not any(
        TYPE_CLASS[ft["type"]] == c and math.hypot(p["x"] - ft["x"], p["y"] - ft["y"]) <= 4.0 for ft in faults))
    for c in FAULT_CLASSES}
print("%s: %d of %d faults found, %d false alert(s) (%s, conf %.2f)" % (
    os.path.basename(a.model), len(found), len(faults), len(result["false_alerts"]), result["confirm"], a.conf))
for f in result["faults"]:
    print("  %-3s %-12s %-5s %d of %d frames in view show its class" % (
        f["id"], f["type"], "found" if f["found"] else "MISSED", f["frames_with_its_class"], f["frames_in_view"]))
for al in result["false_alerts"]:
    print("  false alert: %s at (%.0f, %.0f), frames %d-%d" % (al["cls"], al["x"], al["y"], al["first"], al["last"]))
print("  frames with a fault class where there is none:", result["frames_with_false_class"])
if a.json:
    json.dump(result, open(a.json, "w"), indent=1)
