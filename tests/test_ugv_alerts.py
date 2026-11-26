"""The ground robot's alert node (ros2/.../ugv_alerts.py): its confirmation in metres, where a box lands on the
fence, and the 0.5 m steps. Runs with ROS 2 stand-ins (tests/conftest.py) where ROS 2 is not installed."""
import json
import math

import pytest

from conftest import Msg
from querra_fence_ros.ugv_alerts import LocalConfirmer, UgvAlerts
from querra_fence_ros.ugv_bridge import m_per_deg


# ------------------------------------------------------------------ LocalConfirmer

def feed(c, frames):
    out = {}
    for i, sightings in enumerate(frames):
        new = c.update(sightings)
        if new:
            out[i] = new
    return out


def test_five_of_eight_steps_confirm_and_the_alert_is_their_mean():
    got = feed(LocalConfirmer(), [[("branch", 0.9, 10.0 + 0.2 * i, 2.0)] for i in range(5)])
    assert list(got) == [4]
    a = got[4][0]
    assert (a["class"], a["frames"]) == ("branch", 5)
    assert (a["x"], a["y"]) == (10.4, 2.0)


def test_four_of_eight_steps_do_not():
    assert feed(LocalConfirmer(), [[("branch", 0.9, 10, 2)], []] * 4) == {}


def test_fallen_posts_count_from_their_own_threshold():
    frames = [[("fallen_post", 0.55, 20.0, 1.9)]] * 5
    assert feed(LocalConfirmer(class_conf={"fallen_post": 0.5}), frames) != {}
    assert feed(LocalConfirmer(), frames) == {}


def test_a_class_threshold_does_not_lower_the_others():
    assert feed(LocalConfirmer(class_conf={"fallen_post": 0.5}), [[("branch", 0.55, 20.0, 1.9)]] * 8) == {}


def test_spots_more_than_the_radius_apart_do_not_confirm():
    assert feed(LocalConfirmer(), [[("wire_break", 0.9, 6.0 * i, 1.9)] for i in range(8)]) == {}


def test_a_second_fault_beyond_the_merge_distance_is_a_second_alert():
    c = LocalConfirmer()
    feed(c, [[("wire_break", 0.9, 10.0, 1.9)]] * 5 + [[("wire_break", 0.9, 25.0, 1.9)]] * 5)
    assert [a["x"] for a in c.alerts] == [10.0, 25.0]


def test_posts_and_wires_never_raise_alerts():
    assert feed(LocalConfirmer(), [[("post", 0.99, 1, 1), ("wire", 0.99, 1, 1)]] * 8) == {}


# ------------------------------------------------------------------ the node

def node(x=0.0, y=0.0, yaw=0.0):
    n = UgvAlerts()                 # its own parameter defaults (the stand-in Node hands them back)
    n.publish_markers = lambda stamp: None
    n.pose = (x, y, yaw)
    return n


def test_the_image_centre_is_the_fence_beside_the_robot():
    assert node().on_fence(320) == pytest.approx((0.0, 1.9))


def test_the_right_of_the_image_is_ahead_and_the_left_behind():
    """The camera looks left, so ahead of the robot is to the right of the image; the image edge is 50 deg off."""
    ahead = (1.9 - 0.22) * math.tan(math.radians(50))
    assert node().on_fence(640) == pytest.approx((ahead, 1.9))
    assert node().on_fence(0) == pytest.approx((-ahead, 1.9))


def test_the_fence_turns_with_the_robot():
    """Heading north (+y): the fence on the left is to the west (-x)."""
    assert node(5.0, 5.0, math.pi / 2).on_fence(320) == pytest.approx((5.0 - 1.9, 5.0))


def dets(*items):
    """A Detection2DArray stand-in from (class, conf, image column) items."""
    return Msg(header=Msg(stamp=Msg(sec=7, nanosec=0)),
               detections=[Msg(results=[Msg(hypothesis=Msg(class_id=c, score=s))],
                               bbox=Msg(center=Msg(position=Msg(x=u)))) for c, s, u in items])


def test_one_step_per_half_metre_and_an_alert_on_the_fifth():
    """10 frames per second at 0.8 m/s are 8 cm apart; only the first frame after each 0.5 m of travel counts."""
    n = node()
    for i in range(33):                                  # 4.0 m of travel, 0.125 m per frame (exact in binary)
        n.pose = (0.125 * i, 0.0, 0.0)
        n.on_dets(dets(("wire_break", 0.9, 320)))
    events = [json.loads(m.data) for m in n.pubs["/ugv/alerts/event"].msgs]
    steps = [e for e in events if e.get("src") == "step"]
    alerts = [e for e in events if "class" in e]
    assert len(steps) == 9                               # at 0.0, 0.5, ... 4.0 m
    assert [s["r"][0] for s in steps] == pytest.approx([0.5 * k for k in range(9)])
    assert len(alerts) == 1 and alerts[0]["class"] == "wire_break" and alerts[0]["frames"] == 5
    assert alerts[0]["robot"] == [2.0, 0.0]              # the 5th step
    assert len(n.pubs["/fence/alerts"].msgs) == 1


def test_no_pose_no_steps():
    n = node()
    n.pose = None
    n.on_dets(dets(("wire_break", 0.9, 320)))
    assert n.pubs["/ugv/alerts/event"].msgs == []


def test_metres_per_degree():
    assert m_per_deg(0.0) == pytest.approx((110574.3, 111319.3), abs=0.5)
    assert m_per_deg(45.0) == pytest.approx((111131.8, 78846.8), abs=0.5)
