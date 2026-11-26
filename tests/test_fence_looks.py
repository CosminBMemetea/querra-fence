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
