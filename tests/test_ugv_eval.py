"""tools/ugv_eval.py on a synthetic relay log: patrols, route completion, alerts against faults, steps near faults.
A crash in its alert scoring once stopped a live series; this drives every part of score()."""
import json
import sys

import pytest

import ugv_eval

META = {"route": [[float(i), 0.0] for i in range(101)], "spawn": [0.0, 0.0, 0.0],   # dense, like forest_meta's
        "faults": [{"id": "F1", "type": "wire_break", "x": 30.0, "y": 1.9},
                   {"id": "F2", "type": "post_down", "x": 60.0, "y": 1.9},
                   {"id": "F3", "type": "branch_short", "x": 90.0, "y": 1.9}]}


def log():
    rows = [{"k": "event", "src": "patrol", "state": "driving", "wall": 0.0, "pose_topic": "/ugv/slam_pose"}]
    for i in range(101):                                     # 1 m/s along the route, truth, odometry and SLAM
        rows.append({"k": "truth", "wall": float(i), "x": float(i), "y": 0.0, "yaw": 0.0})
        rows.append({"k": "odom", "wall": float(i), "x": i * 1.01, "y": 0.0})
        rows.append({"k": "pose", "src": "slam", "wall": float(i), "x": i + 0.2, "y": 0.0})
        rows.append({"k": "gps", "wall": float(i), "mode": 3, "err_m": 2.0, "cover": 0.7})
    for j in range(201):                                     # the alert node's steps, every 0.5 m
        x, s = 0.5 * j, []
        if 58.0 <= x <= 62.0:
            s.append(["fallen_post", 0.55, 60.0, 1.9])       # counts: fallen posts from 0.5
        if 28.0 <= x <= 32.0:
            s.append(["wire_break", 0.6, 30.0, 1.9])         # does not: broken wires from 0.7
        rows.append({"k": "event", "src": "step", "wall": x, "r": [x, 0.0], "s": s})
    rows += [{"k": "event", "src": "alert", "wall": 31.0, "id": 1, "class": "wire_break", "x": 31.0, "y": 1.9, "max_conf": 0.9},
             {"k": "event", "src": "alert", "wall": 61.0, "id": 2, "class": "fallen_post", "x": 60.4, "y": 1.9, "max_conf": 0.6},
             {"k": "event", "src": "alert", "wall": 75.0, "id": 3, "class": "branch", "x": 75.0, "y": 1.9, "max_conf": 0.8}]
    rows.append({"k": "event", "src": "patrol", "state": "done", "wall": 100.0, "obstacle_stops": 0})
    return sorted(rows, key=lambda r: r["wall"])


def test_one_patrol_from_driving_to_done():
    p = ugv_eval.patrols(log())
    assert len(p) == 1 and p[0][:3] == (0.0, 100.0, "/ugv/slam_pose") and p[0][3]["state"] == "done"


@pytest.fixture(scope="module")
def result():
    rows = log()
    return ugv_eval.score(rows, META, *ugv_eval.patrols(rows)[0])


def test_route_and_localisation(result):
    assert result["result"] == "done"
    assert result["route"]["completion_pct"] == pytest.approx(99.0, abs=1.0)
    assert result["route"]["cross_track_m"]["max"] == 0.0
    assert result["localisation_error_m"]["slam"]["median"] == 0.2
    assert result["odom_drift_m"]["end"] == 1.0
    assert result["gnss"]["fix_pct"] == 100.0 and result["gnss"]["by_cover"]["dense (>=0.6)"]["share_pct"] == 100.0


def test_alerts_against_the_faults(result):
    al = result["alerts"]
    assert (al["count"], al["faults_found"], al["found"], al["false"]) == (3, 2, ["F1", "F2"], 1)
    false = [a for a in al["list"] if not a["fault"]][0]
    assert false["class"] == "branch" and false["nearest_fault_m"] == 15.0      # F3 is a branch, but 15 m away


def test_steps_near_each_fault_and_their_thresholds(result):
    f = {x["id"]: x for x in result["faults_in_view"]}
    assert f["F2"]["steps_in_view"] == 15                   # robot within 4 m of a fault 1.9 m off the route
    assert f["F2"]["steps_with_its_class"] == 9             # x 58-62: fallen posts from conf 0.5
    assert f["F1"]["steps_with_its_class"] == 0             # 0.6 is below the broken wire's 0.7
    assert f["F3"]["steps_with_its_class"] == 0


def test_the_command_line_prints_and_writes_the_summary(tmp_path, monkeypatch, capsys):
    """main() end to end: on 2026-11-25 a loop variable named like the parsed arguments crashed it after scoring."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in log()))
    (tmp_path / "meta.json").write_text(json.dumps(META))
    monkeypatch.setattr(ugv_eval, "META", str(tmp_path / "meta.json"))
    monkeypatch.setattr(sys, "argv", ["ugv_eval.py", str(run), "--json"])
    ugv_eval.main()
    out = capsys.readouterr().out
    assert "1 patrol(s)" in out and "2 of 3 faults found (F1, F2), 1 false alert(s)" in out
    assert "F2 9 of 15" in out
    assert json.loads((run / "summary.json").read_text())["patrols"][0]["alerts"]["faults_found"] == 2
