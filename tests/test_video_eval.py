"""tools/video_eval.py without a video: DJI's subtitle file, the drone's track from it, and confirming by frames."""
import importlib.util
import sys
import types

import pytest

if importlib.util.find_spec("ultralytics") is None:       # GitHub: no model needed for these tests
    sys.modules["ultralytics"] = types.SimpleNamespace(YOLO=object)
import video_eval as ve  # noqa: E402

M = ve.M_PER_DEG


def block(i, t, lat, lon, alt=12.0, lon_key="longitude"):
    s, ms = int(t), int(round((t - int(t)) * 1000))
    return ("%d\n00:00:%02d,%03d --> 00:00:%02d,%03d\n<font size=\"28\">FrameCnt: %d, DiffTime: 33ms\n2026-11-25 12:00:%02d.%03d\n"
            "[iso: 100] [shutter: 1/1000.0] [fnum: 1.7] [ev: 0] [color_md: default] [focal_len: 24.00] [latitude: %.6f] "
            "[%s: %.6f] [rel_alt: %.3f abs_alt: 512.300] [ct: 5500] </font>\n"
            % (i, s, ms, s, ms + 33, i, s, ms, lat, lon_key, lon, alt))


def srt(tmp_path, blocks):
    p = tmp_path / "DJI_0001.SRT"
    p.write_text("\n".join(blocks), encoding="utf-8")
    return str(p)


def test_dji_subtitles_are_read(tmp_path):
    rows = ve.read_srt(srt(tmp_path, [block(1, 0.0, 47.0, 8.0), block(2, 1.5, 47.00001, 8.0, 11.5)]))
    assert rows == [(0.0, 47.0, 8.0, 12.0), (1.5, 47.00001, 8.0, 11.5)]


def test_the_misspelt_longitude_of_some_firmware(tmp_path):
    rows = ve.read_srt(srt(tmp_path, [block(1, 0.0, 47.0, 8.0, lon_key="longtitude")]))
    assert rows[0][2] == 8.0


def test_zero_zero_is_no_fix(tmp_path):
    rows = ve.read_srt(srt(tmp_path, [block(1, 0.0, 0.0, 0.0), block(2, 1.0, 47.0, 8.0)]))
    assert rows[0][1:3] == (None, None)
    assert len(ve.Track(rows).rows) == 1


def track(dn, de, n=6):
    """A drone moving dn m north and de m east per second, one subtitle per second."""
    lat0 = 47.0
    kx = M * ve.math.cos(ve.math.radians(lat0))
    return ve.Track([(float(i), lat0 + i * dn / M, 8.0 + i * de / kx, 12.0) for i in range(n)])


def test_course_and_speed_over_ground():
    lat, lon, alt, course, speed = track(3.0, 0.0).at(2.0)
    assert course == pytest.approx(0.0, abs=0.1) and speed == pytest.approx(3.0, abs=0.01)
    assert track(0.0, 3.0).at(2.0)[3] == pytest.approx(90.0, abs=0.1)
    assert track(-3.0, 0.0).at(2.0)[3] == pytest.approx(180.0, abs=0.1)


def test_hovering_has_no_course():
    assert track(0.0, 0.0).at(2.0)[3] is None


def test_no_position_far_from_any_subtitle():
    assert track(3.0, 0.0, n=3).at(10.0) is None


# ------------------------------------------------------------------ FrameConfirmer (no subtitles)

def det(cls="branch", conf=0.9):
    return {"class": cls, "conf": conf, "box_xyxy": [0, 0, 10, 10]}


def run(c, frames):
    out = {}
    for i, dets in enumerate(frames):
        new = c.update(dets, {"t": i / 2.0, "frame": i})
        if new:
            out[i] = new
    return out


def test_five_of_eight_consecutive_frames():
    got = run(ve.FrameConfirmer(), [[det()], [], [det()], [det()], [det()], [], [det()]])
    assert list(got) == [6] and got[6][0]["t"] == 3.0


def test_sightings_soon_after_an_alert_belong_to_it():
    c = ve.FrameConfirmer(merge=4)
    got = run(c, [[det()]] * 5 + [[]] * 3 + [[det()]] * 6)
    assert list(got) == [4]                     # frames 8-13: each within 4 frames of the last sighting
    assert c.alerts[0]["sightings"] == 11


def test_a_new_alert_after_the_merge_gap():
    got = run(ve.FrameConfirmer(merge=4), [[det()]] * 5 + [[]] * 8 + [[det()]] * 5)
    assert list(got) == [4, 17]
