"""The drone's alert confirmation (tools/confirm.py, and its copy that runs on the Jetson): where a box lands on the
ground, and when sightings become an alert."""
import ast
import math
import os

import pytest

import confirm
from confirm import AlertConfirmer, ground_point

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAT, LON = 47.0, 8.0
CENTRE = (320, 200, 320, 200)          # a box at the image centre of the 640x400 drone camera


def offset_m(p, q):
    """(north, east) in metres from p to q."""
    return ((q[0] - p[0]) * confirm.M_PER_DEG_LAT,
            (q[1] - p[1]) * confirm.M_PER_DEG_LAT * math.cos(math.radians(p[0])))


# ------------------------------------------------------------------ ground_point

def test_the_image_centre_lands_ahead_at_the_pitch_distance():
    n, e = offset_m((LAT, LON), ground_point(LAT, LON, 12.0, 0.0, CENTRE))
    assert n == pytest.approx(12.0 / math.tan(math.radians(55.0)), abs=0.01)    # 8.40 m ahead
    assert e == pytest.approx(0.0, abs=1e-6)


def test_the_heading_turns_the_point():
    n, e = offset_m((LAT, LON), ground_point(LAT, LON, 12.0, 90.0, CENTRE))
    assert n == pytest.approx(0.0, abs=1e-6)
    assert e == pytest.approx(8.40, abs=0.01)


def test_a_box_right_of_centre_lands_to_the_right():
    n, e = offset_m((LAT, LON), ground_point(LAT, LON, 12.0, 0.0, (420, 200, 420, 200)))
    assert e > 1.0 and n > 8.0


def test_above_the_horizon_there_is_no_ground_hit():
    assert ground_point(LAT, LON, 12.0, 0.0, (320, 0, 320, 0), pitch_deg=5.0) == (LAT, LON)


def test_without_height_or_heading_the_drone_position_is_used():
    assert ground_point(LAT, LON, 0.5, 0.0, CENTRE) == (LAT, LON)
    assert ground_point(LAT, LON, 12.0, None, CENTRE) == (LAT, LON)
    assert ground_point(None, LON, 12.0, 0.0, CENTRE) is None


def test_the_camera_geometry_reaches_the_alerts():
    """The Mini 4 Pro's gimbal is not the simulated drone's: AlertConfirmer(cam=) must reach ground_point."""
    c = AlertConfirmer(cam={"pitch_deg": 80.0})
    for i in range(5):
        c.update([det()], LAT, LON, 12.0, 0.0)
    n, _ = offset_m((LAT, LON), (c.alerts[0]["lat"], c.alerts[0]["lon"]))
    assert n == pytest.approx(12.0 / math.tan(math.radians(80.0)), abs=0.02)


# ------------------------------------------------------------------ AlertConfirmer

def det(cls="wire_break", conf=0.9, box=CENTRE):
    return {"class": cls, "conf": conf, "box_xyxy": box}


def run(c, frames, step_m=0.0):
    """Feed frames (lists of detections), the drone moving step_m north per frame. Returns {frame: new alerts}."""
    out = {}
    for i, dets in enumerate(frames):
        new = c.update(dets, LAT + i * step_m / confirm.M_PER_DEG_LAT, LON, 12.0, 0.0, {"frame": i})
        if new:
            out[i] = new
    return out


def test_five_of_eight_frames_confirm_on_the_fifth():
    got = run(AlertConfirmer(), [[det()], [], [det()], [det()], [], [det()], [det()], [det()]])
    assert list(got) == [6]
    a = got[6][0]
    assert (a["class"], a["frames"], a["frame"]) == ("wire_break", 5, 6)


def test_four_of_eight_frames_do_not():
    assert run(AlertConfirmer(), [[det()], [], [det()], [], [det()], [], [det()], [], [], [det()]]) == {}


def test_sightings_below_the_threshold_do_not_count():
    assert run(AlertConfirmer(), [[det(conf=0.69)]] * 8) == {}


def test_a_class_threshold_replaces_conf_for_that_class_only():
    """class_conf wire_break 0.75: a break seen at 0.72 no longer counts, a branch at 0.72 still does."""
    c = AlertConfirmer(class_conf={"wire_break": 0.75})
    run(c, [[det(conf=0.72), det(cls="branch", conf=0.72)]] * 8)
    assert [a["class"] for a in c.alerts] == ["branch"]


def test_a_class_threshold_can_be_lower_than_conf():
    assert list(run(AlertConfirmer(class_conf={"fallen_post": 0.5}), [[det(cls="fallen_post", conf=0.55)]] * 5)) == [4]


def test_class_thresholds_parse_from_text():
    assert confirm.parse_class_conf("wire_break=0.75, fallen_post=0.5") == {"wire_break": 0.75, "fallen_post": 0.5}
    assert confirm.parse_class_conf("") == {}


def test_classes_that_are_not_faults_are_ignored():
    assert run(AlertConfirmer(), [[det(cls="post")]] * 8) == {}


def test_sightings_at_an_alert_update_it_instead_of_raising_another():
    c = AlertConfirmer()
    got = run(c, [[det()]] * 5 + [[det(conf=0.97)]] * 5)
    assert list(got) == [4]
    assert len(c.alerts) == 1
    assert c.alerts[0]["sightings"] == 10 and c.alerts[0]["max_conf"] == 0.97


def test_later_sightings_refine_the_position():
    """The alert moves to the mean of every sighting matched to it, not only the five that confirmed it: the first
    sightings come from far ahead and are the least accurate (on the recorded mission alerts moved from 2-6 m off
    their fault to 0.4-1.4 m)."""
    far, near = (320, 200, 320, 200), (320, 300, 320, 300)     # 8.40 m and 5.07 m ahead of the drone
    c = AlertConfirmer()
    run(c, [[det(box=far)]] * 5 + [[det(box=near)]] * 15)
    assert len(c.alerts) == 1 and c.alerts[0]["sightings"] == 20
    n_far, _ = offset_m((LAT, LON), ground_point(LAT, LON, 12.0, 0.0, far))
    n_near, _ = offset_m((LAT, LON), ground_point(LAT, LON, 12.0, 0.0, near))
    n, e = offset_m((LAT, LON), (c.alerts[0]["lat"], c.alerts[0]["lon"]))
    assert n == pytest.approx((5 * n_far + 15 * n_near) / 20, abs=0.02)
    assert e == pytest.approx(0.0, abs=0.01)


def test_another_class_at_the_same_spot_is_its_own_alert():
    c = AlertConfirmer()
    run(c, [[det(), det(cls="branch")]] * 5)
    assert sorted(a["class"] for a in c.alerts) == ["branch", "wire_break"]


def test_sightings_far_apart_do_not_confirm():
    """The drone moves 20 m per frame: the same pixel is a different place on the ground every time."""
    assert run(AlertConfirmer(), [[det()]] * 8, step_m=20.0) == {}


def test_sightings_within_the_radius_confirm_while_moving():
    got = run(AlertConfirmer(), [[det()]] * 8, step_m=0.5)
    assert list(got) == [4]


# ------------------------------------------------------------------ the Jetson's copy

def logic(path):
    """The AST of the confirmation logic, without docstrings (comments are not in the AST)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in ("ground_point", "dist_m", "AlertConfirmer"):
            for n in ast.walk(node):
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                        and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                    n.body = n.body[1:] or [ast.Pass()]
            out[node.name] = ast.dump(node)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("FAULTS", "M_PER_DEG_LAT"):
            out[node.targets[0].id] = ast.dump(node)
    return out


def test_the_jetson_copy_has_the_same_logic():
    """ros2/.../confirm.py runs in flight; tools/confirm.py scores offline. If they drift, offline scores stop
    predicting the Jetson."""
    tools = logic(os.path.join(ROOT, "tools", "confirm.py"))
    ros = logic(os.path.join(ROOT, "ros2", "src", "querra_fence_ros", "querra_fence_ros", "confirm.py"))
    assert set(tools) == {"FAULTS", "M_PER_DEG_LAT", "ground_point", "dist_m", "AlertConfirmer"}
    assert tools == ros
