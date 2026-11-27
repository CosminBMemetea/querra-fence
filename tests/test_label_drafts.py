"""tools/label_drafts.py: the review server's API, what it writes, and what it refuses."""
import http.client
import http.server
import json
import os
import sys
import threading

import pytest

import label_drafts as ld


@pytest.fixture
def server(tmp_path):
    d = tmp_path / "walk"
    (d / "images" / "all").mkdir(parents=True)
    (d / "labels" / "all").mkdir(parents=True)
    (d / "drafts").mkdir()
    for i in range(3):
        (d / "images" / "all" / ("w_%05d.jpg" % i)).write_bytes(b"\xff\xd8 not a real jpeg \xff\xd9")
    (d / "drafts" / "w_00001.txt").write_text("2 0.500000 0.500000 0.200000 0.100000 0.810\n")
    ld.save(str(d / "meta.json"), {"times": {"w_00000.jpg": 0.0, "w_00001.jpg": 2.0}, "drafts": {"model": "~/m.pt", "conf": 0.25}})
    ld.write_yaml(str(d))
    H = type("H", (ld.Handler,), {"d": str(d)})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    H.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield d, H.port
    srv.shutdown()
    srv.server_close()


def call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    c.request(method, path, body=json.dumps(body) if isinstance(body, (dict, list)) else body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, (json.loads(data) if r.getheader("Content-Type", "").startswith("application/json") else data), r


def save(port, name, status, boxes=()):
    return call(port, "POST", "/api/save", {"name": name, "status": status, "boxes": list(boxes)})


def test_state_lists_the_frames(server):
    d, port = server
    st, body, _ = call(port, "GET", "/api/state")
    assert st == 200 and body["name"] == "walk" and body["classes"][3] == "fallen_post"
    assert [(f["name"], f["t"], f["status"]) for f in body["frames"]] == [
        ("w_00000.jpg", 0.0, "todo"), ("w_00001.jpg", 2.0, "todo"), ("w_00002.jpg", None, "todo")]


def test_a_frame_comes_with_its_drafts_and_image(server):
    d, port = server
    st, body, _ = call(port, "GET", "/api/frame?name=w_00001.jpg")
    assert st == 200 and body["draft"] == [[2, 0.5, 0.5, 0.2, 0.1, 0.81]] and body["label"] is None
    st, data, r = call(port, "GET", "/img?name=w_00001.jpg")
    assert st == 200 and r.getheader("Content-Type") == "image/jpeg" and data.startswith(b"\xff\xd8")


def test_saving_writes_yolo_labels_and_the_test_list(server):
    d, port = server
    st, body, _ = save(port, "w_00001.jpg", "done", [[3, 0.5, 0.5, 0.2, 0.1], [0, 0.1, 0.5, 0.05, 0.6]])
    assert st == 200 and body == {"ok": True, "done": 1}
    assert (d / "labels" / "all" / "w_00001.txt").read_text() == \
        "3 0.500000 0.500000 0.200000 0.100000\n0 0.100000 0.500000 0.050000 0.600000\n"
    assert (d / "reviewed.txt").read_text() == str(d / "images" / "all" / "w_00001.jpg") + "\n"
    review = json.loads((d / "review.json").read_text())
    assert review["w_00001.jpg"]["status"] == "done" and review["w_00001.jpg"]["boxes"] == 2
    st, body, _ = call(port, "GET", "/api/frame?name=w_00001.jpg")
    assert body["status"] == "done" and body["label"] == [[3, 0.5, 0.5, 0.2, 0.1], [0, 0.1, 0.5, 0.05, 0.6]]


def test_boxes_are_clipped_to_the_image_and_empty_ones_dropped(server):
    d, port = server
    save(port, "w_00000.jpg", "done", [[1, 0.95, 0.5, 0.2, 0.2], [1, 0.5, 0.5, 0.0, 0.3]])
    c, cx, cy, w, h = (float(v) for v in (d / "labels" / "all" / "w_00000.txt").read_text().split())
    assert c == 1 and cx + w / 2 == pytest.approx(1.0) and w == pytest.approx(0.15)


def test_an_empty_frame_is_a_reviewed_frame(server):
    d, port = server
    save(port, "w_00002.jpg", "done", [])
    assert (d / "labels" / "all" / "w_00002.txt").read_text() == ""
    assert "w_00002.jpg" in (d / "reviewed.txt").read_text()


def test_skip_and_unreview_take_the_frame_out_of_the_test_set(server):
    d, port = server
    save(port, "w_00001.jpg", "done", [[2, 0.5, 0.5, 0.1, 0.1]])
    save(port, "w_00001.jpg", "skip")
    assert not (d / "labels" / "all" / "w_00001.txt").exists() and (d / "reviewed.txt").read_text() == ""
    assert json.loads((d / "review.json").read_text())["w_00001.jpg"]["status"] == "skip"
    save(port, "w_00001.jpg", "todo")
    assert "w_00001.jpg" not in json.loads((d / "review.json").read_text())


@pytest.mark.parametrize("body", [
    {"name": "../meta.json", "status": "done", "boxes": []},             # not a frame
    {"name": "w_00000.jpg", "status": "done", "boxes": [[7, 0.5, 0.5, 0.1, 0.1]]},   # no class 7
    {"name": "w_00000.jpg", "status": "maybe", "boxes": []},
    {"name": "w_00000.jpg", "status": "done", "boxes": [["x", 1, 1, 1, 1]]},
    "not json",
])
def test_bad_saves_are_refused(server, body):
    d, port = server
    st, _, _ = call(port, "POST", "/api/save", body)
    assert st == 400
    assert not (d / "labels" / "all" / "w_00000.txt").exists()


def test_only_its_own_page_may_talk_to_it(server):
    d, port = server
    assert call(port, "GET", "/api/state", headers={"Host": "evil.example:%d" % port})[0] == 403   # DNS rebinding
    st, _, _ = call(port, "POST", "/api/save", json.dumps({"name": "w_00000.jpg", "status": "done", "boxes": []}),
                    {"Content-Type": "text/plain"})                  # a cross-site form or fetch without preflight
    assert st == 403 and not (d / "labels" / "all" / "w_00000.txt").exists()


def test_only_frames_are_served(server):
    d, port = server
    for q in ("../meta.json", "..%2Fmeta.json", "w_00009.jpg", ""):
        assert call(port, "GET", "/img?name=" + q)[0] == 404


def test_read_boxes(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("1 0.5 0.5 0.2 0.2 0.9\n\n3 0.1 0.2 0.3 0.4\n")
    assert ld.read_boxes(str(p)) == [[1, 0.5, 0.5, 0.2, 0.2], [3, 0.1, 0.2, 0.3, 0.4]]
    assert ld.read_boxes(str(p), True) == [[1, 0.5, 0.5, 0.2, 0.2, 0.9], [3, 0.1, 0.2, 0.3, 0.4, 1.0]]
    assert ld.read_boxes(str(tmp_path / "missing.txt")) is None


# ------------------------------------------------------------------ drafting with several models

class _Fake:
    names = {}

    def __init__(self, path):
        self.path, self.prompts = path, None

    def set_classes(self, prompts):
        self.prompts = prompts
        self.names = dict(enumerate(prompts))


def _models(monkeypatch, names):
    import types
    yolo = type("YOLO", (_Fake,), {"names": names})
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=yolo, YOLOWorld=_Fake))
    return types.SimpleNamespace(conf=0.4, world_conf=0.15, prompts="post=fence post|wooden post;cow=cow")


def test_a_coco_model_drafts_only_the_animals(monkeypatch):
    a = _models(monkeypatch, {0: "person", 1: "sheep", 2: "cow", 3: "car"})
    _, mapping, conf, _ = ld.drafter("coco.pt", a, first=False)
    assert mapping == {1: ld.CLASSES.index("sheep"), 2: ld.CLASSES.index("cow")} and conf == 0.4


def test_a_model_can_be_kept_to_some_classes(monkeypatch):
    a = _models(monkeypatch, dict(enumerate(ld.CLASSES)))
    _, mapping, _, _ = ld.drafter("ground.pt@wire_break,branch", a, first=True)
    assert mapping == {2: 2, 4: 4}
    with pytest.raises(SystemExit):
        ld.drafter("ground.pt@wire_brake", a, first=True)


def test_a_world_model_drafts_what_its_prompts_name(monkeypatch):
    a = _models(monkeypatch, {})
    m, mapping, conf, _ = ld.drafter("yolov8s-worldv2.pt", a, first=False)
    assert m.prompts == ["fence post", "wooden post", "cow"]
    assert mapping == {0: 0, 1: 0, 2: ld.CLASSES.index("cow")} and conf == 0.15


def test_overlapping_drafts_of_one_class_keep_the_surer():
    boxes = [(0, [0.5, 0.5, 0.2, 0.4], 0.6), (0, [0.51, 0.5, 0.2, 0.4], 0.9), (5, [0.5, 0.5, 0.2, 0.4], 0.7),
             (0, [0.1, 0.5, 0.05, 0.4], 0.3)]
    kept = ld.merge(boxes)
    assert [(c, s) for c, _, s in kept] == [(0, 0.9), (5, 0.7), (0, 0.3)]
