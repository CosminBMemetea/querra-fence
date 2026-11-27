"""The simulator's fence looks (sim/gen_world.py) and the supersampled camera's averaging (tools/make_ground_dataset.py):
the classic look stays exactly what every model so far was trained on, the real looks are real sizes, and a wire
thinner than a pixel becomes a faint line, not nothing."""
import os
import re
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import geo  # noqa: E402
import gen_world  # noqa: E402


@pytest.fixture
def look(monkeypatch):
    def use(name):
        monkeypatch.setattr(gen_world, "FENCE_LOOK", name)
        return gen_world.build_fence(geo.Fence(geo.load_config(os.path.join(ROOT, "forest.json")))).xml()
    return use


def radii(xml):
    return [float(r) for r in re.findall(r"<cylinder><radius>([\d.]+)</radius>", xml)]


def test_classic_is_the_trained_look(look):
    xml = look("classic")
    assert 0.018 in radii(xml)                                         # 3.6 cm rods
    assert "<emissive>0.550 0.420 0.050 1</emissive>" in xml           # glowing yellow, live strands
    assert gen_world.WIRE_DEAD in xml                                  # grey strands without current after a break


@pytest.mark.parametrize("name, size", [("steel", 0.0013), ("polywire", 0.0015), ("polyrope", 0.003)])
def test_real_wire_is_its_real_size_and_does_not_glow(look, name, size):
    xml = look(name)
    thin = [r for r in radii(xml) if r < 0.01]
    assert thin and set(thin) == {size}
    assert gen_world.WIRE not in xml and gen_world.WIRE_DEAD not in xml    # one colour, live or dead


def test_tape_is_a_ribbon_on_edge(look):
    xml = look("polytape")
    tapes = re.findall(r"<box><size>[\d.]+ 0\.002 0\.040</size></box>", xml)
    assert len(tapes) > 100 and gen_world.WIRE not in xml


def test_every_look_has_the_same_strands(look):
    """Only the drawing changes: the same number of conductor pieces (and so the same labels) in every look."""
    n = {name: look(name).count("<visual") for name in gen_world.FENCE_LOOKS}
    assert len(set(n.values())) == 1


# ------------------------------------------------------------------ supersampling

@pytest.fixture(scope="module")
def mg():
    np = pytest.importorskip("numpy")
    for m in ("gz", "gz.transport13", "gz.msgs10", "gz.msgs10.image_pb2", "gz.msgs10.pose_pb2", "gz.msgs10.boolean_pb2"):
        sys.modules.setdefault(m, types.SimpleNamespace(Node=object, Image=object, Pose=object, Boolean=object))
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import make_ground_dataset
    return make_ground_dataset, np


def test_a_wire_thinner_than_a_pixel_becomes_a_faint_line(mg):
    m, np = mg
    a = np.full((40, 40, 3), 60, np.uint8)
    a[:, 17] = 230                                                     # 1 px of 4: a quarter of the light
    d = m.downsample(a, 4)
    assert d.shape == (10, 10, 3)
    assert d[0, 4, 0] == 132 and d[0, 3, 0] == 60 and d[0, 5, 0] == 60    # averaged in linear light, not 102 in sRGB


def test_flat_areas_do_not_change(mg):
    m, np = mg
    assert (m.downsample(np.full((9, 9, 3), 123, np.uint8), 3) == 123).all()


def test_the_supersampled_camera_sends_fewer_frames(mg):
    """At 30 per second the 4x frames (12 MB) piled up faster than Python read them and filled memory and swap."""
    m, _ = mg
    assert m.cam_rate(1) == 30
    assert all(m.cam_rate(k) * (m.W * k) * (m.H * k) * 3 <= 50e6 for k in (2, 3, 4))   # about 40 MB/s
    assert "<update_rate>6</update_rate>" in m.cam_xml(3) and "<width>1920</width>" in m.cam_xml(3)


# ------------------------------------------------------------------ the drone's dataset tool (tools/make_dataset.py)

@pytest.fixture
def drone_fence(mg, monkeypatch):
    """The drone dataset's fence (its own builder, with dead-wire colours and break shapes) for one random farm."""
    md = sys.modules["make_dataset"]
    cfg, _ = md.random_layout(161)

    def use(name):
        monkeypatch.setattr(gen_world, "FENCE_LOOK", name)
        return md.build_fence_v2(geo.Fence(cfg), cfg["_render"]).xml()
    return use


def test_the_drone_fence_keeps_its_look_in_classic(drone_fence):
    xml = drone_fence("classic")
    assert {0.018, 0.012} <= set(radii(xml))                           # strands and the gate wire as before
    assert "<emissive>0.550 0.420 0.050 1</emissive>" in xml


@pytest.mark.parametrize("name, size", [("steel", 0.0013), ("polywire", 0.0015), ("polyrope", 0.003)])
def test_the_drone_fence_draws_real_wire(drone_fence, name, size):
    xml = drone_fence(name)
    assert set(r for r in radii(xml) if r < 0.01) == {size}             # strands, broken pieces and the gate wire
    assert 0.018 not in radii(xml) and gen_world.WIRE not in xml and gen_world.WIRE_DEAD not in xml


def test_the_drone_fence_has_the_same_strands_in_every_look(drone_fence):
    assert len({drone_fence(name).count("<visual") for name in gen_world.FENCE_LOOKS}) == 1


def test_the_drone_camera_supersamples(mg):
    m, np = mg
    md = sys.modules["make_dataset"]
    assert md.CAM_XML == md.cam_xml(1) and "<width>640</width>" in md.CAM_XML and "<update_rate>30</update_rate>" in md.CAM_XML
    assert "<width>1920</width><height>1200</height>" in md.cam_xml(3) and "<update_rate>6</update_rate>" in md.cam_xml(3)
    fr = md.Frames(2)
    raw = np.full((md.H * 2, md.W * 2, 3), 60, np.uint8)
    raw[:, 9] = 230                                                    # 1 px of 2 at the 2x size
    fr.cb(types.SimpleNamespace(width=md.W * 2, height=md.H * 2, step=md.W * 2 * 3, data=raw.tobytes()))
    fr.cb(types.SimpleNamespace(width=md.W, height=md.H, step=md.W * 3, data=b""))   # a frame of the wrong size: ignored
    img = fr.wait_new(0, k=1, timeout=0.1)
    assert img.shape == (md.H, md.W, 3) and img[0, 4, 0] > 150 and img[0, 5, 0] == 60


def test_a_wider_ground_camera_keeps_the_labels_and_slows_its_frames(mg, monkeypatch):
    """--width: the same lens with more pixels. Labels are in fractions of the frame, so they must not move; the
    larger frames come fewer per second, colour and depth."""
    m, np = mg
    pts = np.array([[3.0, 0.4, 0.9], [3.0, 0.2, 0.5], [3.2, -0.1, 0.2]])
    objs = [("post", pts, 0.0)]
    R, c = np.eye(3), np.array([0.0, 0.0, 0.7])
    small = m.labels_for(objs, c, R, None)
    monkeypatch.setattr(m, "W", m.W); monkeypatch.setattr(m, "H", m.H)
    monkeypatch.setattr(m, "FX", m.FX); monkeypatch.setattr(m, "SCALE", m.SCALE)
    m.set_width(1920)
    assert (m.W, m.H, m.SCALE) == (1920, 1200, 3.0)
    big = m.labels_for(objs, c, R, None)
    assert small and len(big) == len(small) and np.allclose(big[0][1:], small[0][1:], atol=0.002)
    xml = m.cam_xml(2)
    assert "<width>3840</width>" in xml and "<update_rate>2</update_rate>" in xml        # colour: 3840x2400, 55 MB/s
    assert "<update_rate>6</update_rate><topic>/ds_cam/depth" in xml                    # depth: 1920x1200 floats
