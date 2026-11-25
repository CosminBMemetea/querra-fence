"""Model registry of the fence detector: validates ml/models.json and ml/datasets.json, and keeps the model table in
ml/README.md in sync with them.

    python3 tools/model_registry.py                  # validate, print the table
    python3 tools/model_registry.py --write          # validate, rewrite the table in ml/README.md
    python3 tools/model_registry.py --check DIR ...  # compare model files found in DIR(s) with the registry's sha256

Checks: unique ids, a known status, exactly one default model per list (the drone's "models", the ground robot's
"ground_models"), parents and datasets that exist, frame counts that fit the dataset split, no test split in any
training or validation data, run folders that exist, well-formed hashes.
"""
import argparse
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ML = os.path.join(ROOT, "ml")
START, END = "<!-- registry:start -->", "<!-- registry:end -->"
GSTART, GEND = "<!-- ground-registry:start -->", "<!-- ground-registry:end -->"


def load():
    with open(os.path.join(ML, "models.json")) as f:
        reg = json.load(f)
    with open(os.path.join(ML, "datasets.json")) as f:
        ds = {d["id"]: d for d in json.load(f)["datasets"]}
    return reg, ds


def all_models(reg):
    return reg["models"] + reg.get("ground_models", [])


def validate(reg, ds):
    errs, ids = [], [m["id"] for m in all_models(reg)]
    if len(ids) != len(set(ids)):
        errs.append("duplicate model ids")
    for key in ("models", "ground_models"):
        if reg.get(key) and sum(m["status"] == "default" for m in reg[key]) != 1:
            errs.append("exactly one model in %s must have status 'default'" % key)
    for m in all_models(reg):
        w = m["id"] + ": "
        if m["status"] not in reg["statuses"]:
            errs.append(w + "unknown status " + m["status"])
        if m["parent"] not in ids and not m["parent"].startswith("yolo11n"):
            errs.append(w + "unknown parent " + m["parent"])
        if m.get("run") and not os.path.isdir(os.path.join(ROOT, m["run"])):
            errs.append(w + "run folder missing: " + m["run"])
        for role in ("train", "val"):
            items = m["data"].get(role)
            for it in items if isinstance(items, list) else []:
                d = ds.get(it["dataset"])
                sp = d and d["splits"].get(it["split"])
                if not sp:
                    errs.append(w + "unknown dataset split %s:%s" % (it["dataset"], it["split"]))
                    continue
                if sp["role"] == "test":
                    errs.append(w + "test split %s:%s used for %s" % (it["dataset"], it["split"], role))
                if it["frames"] > sp["frames"]:
                    errs.append(w + "%s:%s has %d frames, not %d" % (it["dataset"], it["split"], sp["frames"], it["frames"]))
        for a in m["artefacts"]:
            if not re.fullmatch(r"[0-9a-f]{64}", a["sha256"]):
                errs.append(w + "bad sha256 for " + a["file"])
    return errs


def fmt(x):
    return "–" if x is None else str(x)


def table(reg):
    rows = ["| Model | Status | Date | Trained on | Test mAP50 classic / rich | `wire_break` recall classic / rich "
            "| Mission replay: faults, false alerts | Live classic | Live rich | Run |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for m in reg["models"]:
        s, tr = m["scores"], m["data"]["train"]
        frames = sum(t["frames"] for t in tr)
        trained = "%s frames, %d dataset%s" % (format(frames, ","), len(tr), "s" if len(tr) > 1 else "")
        live = []
        for look in ("classic", "rich"):
            lv = m.get("live", {}).get(look)
            if not lv:
                live.append("–")
            elif "false_alerts" in lv:
                live.append("%s, %d" % (lv["faults_found"], lv["false_alerts"]))
            else:
                live.append("%s, %d false frames" % (lv["faults_found"], lv["false_wire_break_frames"]))
        rep = m.get("mission_replay") or {}
        replay = "%s, %d" % (rep["faults_found"], rep["false_alerts"]) if rep else "–"
        run = "[%s](%s)" % (os.path.basename(m["run"]), os.path.relpath(os.path.join(ROOT, m["run"]), ML)) if m.get("run") else "–"
        rows.append("| **%s** | %s | %s | %s | %s / %s | %s / %s | %s | %s | %s | %s |" % (
            m["id"], m["status"], m["date"], trained,
            fmt(s.get("test_classic_mAP50")), fmt(s.get("test_rich_mAP50")),
            fmt(s.get("test_classic_wire_break_recall")), fmt(s.get("test_rich_wire_break_recall")),
            replay, live[0], live[1], run))
    return "\n".join(rows)


def ground_table(reg):
    rows = ["| Model | Status | Date | Trained on | Test mAP50 | Patrol frames offline: faults, false alerts "
            "| Live patrols: faults, false alerts | Run |", "|---|---|---|---|---|---|---|---|"]
    for m in reg.get("ground_models", []):
        s, tr = m["scores"], m["data"]["train"]
        frames = sum(t["frames"] for t in tr)
        lv = m.get("live", {}).get("forest_patrols")
        live = "%d patrols: %s, %d" % (lv["patrols"], lv["faults_found"], lv["false_alerts"]) if lv else "–"
        run = "[%s](%s)" % (os.path.basename(m["run"]), os.path.relpath(os.path.join(ROOT, m["run"]), ML)) if m.get("run") else "–"
        rows.append("| **%s** | %s | %s | %s frames, %d dataset%s | %s | %s | %s | %s |" % (
            m["id"], m["status"], m["date"], format(frames, ","), len(tr), "s" if len(tr) > 1 else "",
            fmt(s.get("test_mAP50")), (s.get("patrol_offline") or {}).get("conf0.7", "–"), live, run))
    return "\n".join(rows)


def check(reg, dirs):
    want = {}
    for m in all_models(reg):
        for a in m["artefacts"]:
            for name in [a["file"]] + a.get("aliases", []):
                want[name] = (m["id"], a)
    found = bad = 0
    for d in dirs:
        for dp, _, files in os.walk(os.path.expanduser(d)):
            for f in sorted(files):
                if f not in want:
                    continue
                h = hashlib.sha256()
                with open(os.path.join(dp, f), "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                mid, a = want[f]
                ok = h.hexdigest() == a["sha256"]
                found += 1
                bad += not ok
                print("%-4s %-12s %s" % ("ok" if ok else "DIFF", mid, os.path.join(dp, f)))
    print("%d model files checked, %d differ" % (found, bad))
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite the table in ml/README.md")
    ap.add_argument("--check", nargs="+", metavar="DIR", help="hash model files found in these folders")
    args = ap.parse_args()
    reg, ds = load()
    errs = validate(reg, ds)
    for e in errs:
        print("error:", e)
    if errs:
        sys.exit(1)
    if args.check:
        sys.exit(0 if check(reg, args.check) else 1)
    t, g = table(reg), ground_table(reg)
    if args.write:
        p = os.path.join(ML, "README.md")
        s = open(p).read()
        for st, en, tb in ((START, END, t), (GSTART, GEND, g)):
            a, b = s.index(st) + len(st), s.index(en)
            s = s[:a] + "\n" + tb + "\n" + s[b:]
        open(p, "w").write(s)
        print("registry valid; tables written to ml/README.md")
    else:
        print(t + "\n\n" + g)


if __name__ == "__main__":
    main()
