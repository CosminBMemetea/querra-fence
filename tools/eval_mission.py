"""Offline evaluation of a fence detector on a recorded simulated mission (tools/cam_record.py output).

    python tools/eval_mission.py REC_DIR WEIGHTS.pt TAG [--conf 0.35] [--imgsz 416,640] [--class-conf wire_break=0.75]
                                 [--reuse]

Runs the model on every in-flight frame (altitude > 8 m) and reports, per injected fault, how many frames
within 30 m saw it, plus false fault frames far (> 45 m) from it. Then replays the detections through the
multi-frame GPS confirmation (tools/confirm.py) and counts alerts: true if within 15 m of the fault, false
otherwise (distances_m: each alert's distance to the fault of its class). alerts_5of8_conf0.7 is the live
setting on the Jetson. Use --imgsz 416,640 for a static-shape ONNX export. Writes REC_DIR/det_TAG.jsonl and
REC_DIR/eval_TAG.json. Fault positions are those of the default mission (fence.json, seed in the file), read
from the mission report. --class-conf adds alerts_5of8_conf0.7_class_conf: the live rule with some classes at
their own threshold. --reuse reads REC_DIR/det_TAG.jsonl from an earlier run instead of running the model
again (only the confirmation is replayed).
"""
import argparse, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirm import AlertConfirmer, parse_class_conf  # noqa: E402

FAULTS = {"F1": ((45.694249, 21.461850), "wire_break"), "F2": ((45.695039, 21.461562), "fallen_post"),
          "F3": ((45.694893, 21.460361), "branch")}
OF = {c: pos for pos, c in FAULTS.values()}
dist = lambda a, b: math.hypot((a[0] - b[0]) * 111132, (a[1] - b[1]) * 111132 * math.cos(math.radians(a[0])))

ap = argparse.ArgumentParser()
ap.add_argument("rec"); ap.add_argument("weights"); ap.add_argument("tag")
ap.add_argument("--conf", type=float, default=0.35)
ap.add_argument("--imgsz", default="640", help="640, or H,W (416,640 for the exported ONNX)")
ap.add_argument("--class-conf", default="", help="also replay the live rule with these per-class thresholds: wire_break=0.75")
ap.add_argument("--reuse", action="store_true", help="read det_TAG.jsonl from an earlier run instead of running the model")
a = ap.parse_args()
det_path = os.path.join(a.rec, f"det_{a.tag}.jsonl")
if a.reuse:
    rows = [json.loads(l) for l in open(det_path)]
else:
    from ultralytics import YOLO
    rows = [json.loads(l) for l in open(os.path.join(a.rec, "frames.jsonl"))]
    rows = [r for r in rows if (r.get("telemetry") or {}).get("lat") and (r["telemetry"].get("alt_m") or 0) > 8]
    m = YOLO(a.weights)
    with open(det_path, "w") as out:
        for i in range(0, len(rows), 32):
            batch = rows[i:i + 32]
            for r, p in zip(batch, m.predict([os.path.join(a.rec, r["file"]) for r in batch], imgsz=[int(v) for v in a.imgsz.split(",")] if "," in a.imgsz else int(a.imgsz), conf=a.conf, verbose=False)):
                r["detections"] = [{"class": m.names[int(c)], "conf": round(float(s), 3), "box_xyxy": [round(float(v), 1) for v in b]}
                                   for b, c, s in zip(p.boxes.xyxy.tolist(), p.boxes.cls.tolist(), p.boxes.conf.tolist())]
                out.write(json.dumps(r) + "\n")
pos = lambda r: (r["telemetry"]["lat"], r["telemetry"]["lon"])
res = dict(model=a.tag, frames=len(rows))
for k, (p, c) in FAULTS.items():
    near = [r for r in rows if dist(pos(r), p) < 30]
    hit = [r for r in near if any(x["class"] == c for x in r["detections"])]
    res[k] = dict(near=len(near), detected=len(hit), max_conf=max([x["conf"] for r in hit for x in r["detections"] if x["class"] == c] or [0]))
    for th in (0.35, 0.5, 0.7):
        res[f"false_frames_{c}@{th}"] = sum(1 for r in rows if dist(pos(r), p) > 45 and any(x["class"] == c and x["conf"] >= th for x in r["detections"]))
class_conf = parse_class_conf(a.class_conf)
rules = [(1, 1, 0.5, {}, "alerts_1of1"), (3, 5, 0.5, {}, "alerts_3of5"), (5, 8, 0.5, {}, "alerts_5of8"),
         (5, 8, 0.7, {}, "alerts_5of8_conf0.7")] + ([(5, 8, 0.7, class_conf, "alerts_5of8_conf0.7_class_conf")] if class_conf else [])
for n, w, c, cc, key in rules:
    cf = AlertConfirmer(n, w, 5.0, c, class_conf=cc)
    for r in rows:
        t = r["telemetry"]; cf.update(r["detections"], t["lat"], t["lon"], t.get("alt_m"), t.get("heading_deg"))
    d = [dist((x["lat"], x["lon"]), OF[x["class"]]) for x in cf.alerts]
    res[key] = dict(total=len(d), false=sum(1 for x in d if x > 15),
                    faults_alerted=sorted({x["class"] for x, e in zip(cf.alerts, d) if e <= 15}),
                    distances_m=[[x["class"], round(e, 1)] for x, e in zip(cf.alerts, d)])
if class_conf:
    res["class_conf"] = class_conf
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(a.rec, f"eval_{a.tag}.json"), "w"), indent=1)
