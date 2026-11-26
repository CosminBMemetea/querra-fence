"""Phone alerts (ros2/.../notify.py, the phone_alerts node, tools/notify.py): what goes to ntfy and Telegram, the
retries, the rate limit, and the node picking the alert's own camera frame. A local server stands in for both
services: nothing leaves the machine."""
import http.server
import json
import math
import os
import threading
import time
import urllib.parse

import pytest

import conftest
from conftest import Msg
from querra_fence_ros import notify

TOKEN = "123456:SECRET-bot-token"


class Fake:
    """Records every request; answers from `script` (a list of (status, body, headers)) and then 200."""

    def __init__(self):
        self.requests, self.script, fake = [], [], self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def handle_one(self):
                n = int(self.headers.get("Content-Length") or 0)
                u = urllib.parse.urlparse(self.path)
                fake.requests.append({"method": self.command, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
                                      "headers": dict(self.headers), "body": self.rfile.read(n)})
                status, body, headers = fake.script.pop(0) if fake.script else (200, {"ok": True, "result": {}}, {})
                data = json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = handle_one

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def wait(self, n, timeout=5):
        t0 = time.time()
        while len(self.requests) < n and time.time() - t0 < timeout:
            time.sleep(0.01)
        return self.requests


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.srv.shutdown()
    f.srv.server_close()


ALERT = {"source": "ground robot", "class": "wire_break", "id": 3, "conf": 0.912, "frames": 5,
         "lat": 47.123456, "lon": 8.654321, "time": time.mktime((2026, 11, 26, 14, 7, 32, 0, 0, -1))}


def jpeg(w=640, h=400):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    return cv2.imencode(".jpg", np.full((h, w, 3), 90, np.uint8))[1].tobytes()


# ------------------------------------------------------------------ text

def test_one_alert_reads_well():
    title, text, url = notify.describe(ALERT)
    assert title == "Broken wire · ground robot"
    assert text == "Alert 3, conf 0.91, 5 frames at 14:07:32\n47.123456, 8.654321"
    assert url == "https://maps.google.com/?q=47.123456,8.654321"


def test_no_position_no_map():
    assert notify.describe(dict(ALERT, lat=math.nan, lon=math.nan))[2] is None
    assert notify.describe(dict(ALERT, lat=None))[2] is None


def test_alerts_sent_together_are_summarised():
    title, text, url = notify.summarise([dict(ALERT, id=i) for i in range(12)])
    assert title == "12 fence alerts · ground robot"
    assert text.count("\n- ") == 9 and text.endswith("... and 2 more")
    assert url.startswith("https://maps.google.com/?q=47.123456")


# ------------------------------------------------------------------ ntfy

def test_ntfy_sends_the_photo_with_title_message_and_map(fake):
    photo = b"\xff\xd8 a photo \xff\xd9"
    notify.Ntfy("querra-abc", server=fake.url, token="tk_secret").send(*notify.describe(ALERT), jpeg=photo)
    r = fake.requests[0]
    assert (r["method"], r["path"], r["body"]) == ("PUT", "/querra-abc", photo)
    assert r["query"]["title"] == "Broken wire · ground robot"                  # UTF-8 through the URL
    assert r["query"]["message"].split("\n")[0] == "Alert 3, conf 0.91, 5 frames at 14:07:32"
    assert (r["query"]["filename"], r["query"]["tags"], r["query"]["priority"]) == ("alert.jpg", "warning", "high")
    assert r["query"]["click"] == "https://maps.google.com/?q=47.123456,8.654321"
    assert r["headers"]["Authorization"] == "Bearer tk_secret"


def test_ntfy_text_only_goes_in_the_body(fake):
    notify.Ntfy("t", server=fake.url, token="me:pw").send("Querra fence", "Phone alerts on.")
    r = fake.requests[0]
    assert (r["method"], r["body"].decode()) == ("POST", "Phone alerts on.") and "message" not in r["query"]
    assert r["headers"]["Authorization"] == "Basic bWU6cHc="


# ------------------------------------------------------------------ Telegram

def test_telegram_sends_the_photo_then_a_map_pin(fake):
    notify.Telegram(TOKEN, 42, api=fake.url).send(*notify.describe(ALERT), jpeg=b"\xff\xd8PHOTO\xff\xd9", lat=ALERT["lat"], lon=ALERT["lon"])
    photo, pin = fake.requests
    assert photo["path"] == "/bot%s/sendPhoto" % TOKEN
    assert b'name="chat_id"\r\n\r\n42' in photo["body"] and b"\xff\xd8PHOTO\xff\xd9" in photo["body"]
    assert "Broken wire · ground robot\nAlert 3".encode() in photo["body"]
    assert pin["path"].endswith("/sendLocation")
    assert urllib.parse.parse_qs(pin["body"].decode()) == {"chat_id": ["42"], "latitude": ["47.123456"], "longitude": ["8.654321"]}


def test_telegram_without_a_photo_or_position(fake):
    notify.Telegram(TOKEN, 42, api=fake.url).send("Querra fence", "Phone alerts on.")
    assert [r["path"].rsplit("/", 1)[1] for r in fake.requests] == ["sendMessage"]


# ------------------------------------------------------------------ delivery

def test_server_errors_are_retried(fake):
    fake.script = [(503, {}, {}), (429, {"ok": False, "parameters": {"retry_after": 0}}, {})]
    n = notify.Notifier({"ntfy": {"topic": "t", "server": fake.url}}, log=lambda m: None, retry_s=(0.01, 0.01, 0.01))
    n.alert(ALERT)
    n.close()
    assert len(fake.requests) == 3 and [x[0] for x in n.sent] == ["ntfy"] and n.failed == []


def test_a_refusal_is_not_retried_and_the_token_never_logged(fake):
    fake.script = [(401, {"ok": False, "error_code": 401, "description": "Unauthorized"}, {})]
    logs = []
    n = notify.Notifier({"telegram": {"bot_token": TOKEN, "chat_id": 42, "api": fake.url}}, log=logs.append, retry_s=(0.01,) * 3)
    n.alert(ALERT)
    n.close()
    assert len(fake.requests) == 1 and n.failed == [("telegram", "Broken wire · ground robot")]
    assert "Unauthorized" in logs[0] and TOKEN not in " ".join(logs)


def test_no_network_names_neither_the_url_nor_the_topic():
    with pytest.raises(notify.SendError) as e:
        notify.Ntfy("querra-private-topic", server="http://127.0.0.1:9", timeout=2).send("t", "m")
    assert e.value.retry and "private" not in str(e.value) and "127.0.0.1" not in str(e.value)


class Recorder:
    name = "rec"

    def __init__(self):
        self.msgs = []

    def send(self, title, text, click=None, jpeg=None, lat=None, lon=None):
        self.msgs.append((title, text, jpeg))


def test_a_burst_then_alerts_that_wait_go_out_together():
    rec = Recorder()
    n = notify.Notifier({"burst": 1, "refill_s": 0.4}, sends=[rec])
    n.alert(ALERT, b"first")
    time.sleep(0.1)
    for i in range(3):
        n.alert(dict(ALERT, id=10 + i), b"photo%d" % i)
    time.sleep(0.8)
    n.close()
    assert [m[0] for m in rec.msgs] == ["Broken wire · ground robot", "3 fence alerts · ground robot"]
    assert rec.msgs[1][2] == b"photo2"                                        # the newest photo


def test_close_sends_what_waits_at_once():
    rec = Recorder()
    n = notify.Notifier({"burst": 1, "refill_s": 600}, sends=[rec])
    n.alert(ALERT)
    time.sleep(0.1)                                                           # the burst: sent alone
    for i in range(2):
        n.alert(dict(ALERT, id=i))
    t0 = time.time()
    n.close()
    assert time.time() - t0 < 2 and [m[0] for m in rec.msgs] == ["Broken wire · ground robot", "2 fence alerts · ground robot"]


def test_backends_come_from_the_settings():
    assert notify.backends({}) == []
    assert [b.name for b in notify.backends({"ntfy": {"topic": "x"}, "telegram": {"bot_token": TOKEN}})] == ["ntfy"]
    assert [b.name for b in notify.backends({"ntfy": {"topic": "x"}, "telegram": {"bot_token": TOKEN, "chat_id": 1}})] == ["ntfy", "telegram"]


def test_the_settings_file(tmp_path, monkeypatch):
    p = tmp_path / "notify.json"
    p.write_text(json.dumps({"ntfy": {"topic": "x"}}))
    monkeypatch.setenv("QUERRA_NOTIFY", str(p))
    assert notify.config_path() == str(p) and notify.load_config() == {"ntfy": {"topic": "x"}}
    assert notify.load_config(str(tmp_path / "missing.json")) is None


def test_the_box_is_drawn_on_the_photo():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    out = notify.annotate(jpeg(), [("wire_break", 0.9, 320, 200, 100, 60), ("post", 0.9, 100, 200, 20, 200)], "wire_break")
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == (400, 640, 3)
    b, g, r = (int(v) for v in img[170, 320])                                 # the top edge of the box: red
    assert r > 200 and g < 120 and b < 120
    assert tuple(int(v) for v in img[200, 100]) == pytest.approx((90, 90, 90), abs=6)   # posts are not drawn
    assert notify.annotate(b"not a jpeg", [], None) == b"not a jpeg"


# ------------------------------------------------------------------ the phone_alerts node

needs_stubs = pytest.mark.skipif(not conftest.STUBBED, reason="builds the node on the ROS 2 stand-ins")


def node(monkeypatch, tmp_path, fake, **params):
    from querra_fence_ros.phone_alerts import PhoneAlerts
    cfg = tmp_path / "notify.json"
    cfg.write_text(json.dumps({"ntfy": {"topic": "querra-test", "server": fake.url}}))
    monkeypatch.setattr(conftest.Node, "overrides", dict({"config": str(cfg), "source": "ground robot",
                                                          "image": "/cam", "announce": False}, **params))
    return PhoneAlerts()


def header(t):
    return Msg(stamp=Msg(sec=int(t), nanosec=int(round((t % 1) * 1e9))))


def alert_msg(t, new=True):
    return Msg(header=header(t), id=3, class_name="wire_break", latitude=47.123456, longitude=8.654321,
               max_conf=0.912, frames=5, sightings=5, is_new=new)


@needs_stubs
def test_the_alert_goes_out_with_its_own_frame_and_box(monkeypatch, tmp_path, fake):
    n = node(monkeypatch, tmp_path, fake)
    frames = {t: jpeg() for t in (10.0, 10.1, 10.2)}
    for t, data in frames.items():
        n.subs["/cam"](Msg(header=header(t), data=data))
        n.subs["/detections"](Msg(header=header(t), detections=[Msg(
            results=[Msg(hypothesis=Msg(class_id="wire_break", score=0.91))],
            bbox=Msg(center=Msg(position=Msg(x=320.0, y=200.0)), size_x=100.0, size_y=60.0))] if t == 10.1 else []))
    n.subs["/fence/alerts"](alert_msg(10.1))
    r = fake.wait(1)[0]
    n.n.close()
    assert r["method"] == "PUT" and r["query"]["title"] == "Broken wire · ground robot"
    assert r["body"] != frames[10.1] and r["body"][:2] == b"\xff\xd8"          # the frame of 10.1 s, with its box drawn


@needs_stubs
def test_updates_of_known_alerts_are_not_sent(monkeypatch, tmp_path, fake):
    n = node(monkeypatch, tmp_path, fake)
    n.subs["/fence/alerts"](alert_msg(5.0, new=False))
    n.n.close()
    assert fake.requests == []


@needs_stubs
def test_without_a_frame_the_alert_still_goes_out(monkeypatch, tmp_path, fake):
    n = node(monkeypatch, tmp_path, fake)
    n.subs["/fence/alerts"](alert_msg(5.0))
    r = fake.wait(1)[0]
    n.n.close()
    assert r["method"] == "POST" and r["body"].decode().startswith("Alert 3, conf 0.91")


@needs_stubs
def test_the_start_message(monkeypatch, tmp_path, fake):
    n = node(monkeypatch, tmp_path, fake, announce=True)
    r = fake.wait(1)[0]
    n.n.close()
    assert r["query"]["title"] == "Querra fence" and b"ground robot" in r["body"]


@needs_stubs
def test_no_settings_no_alerts(monkeypatch, tmp_path, fake):
    from querra_fence_ros.phone_alerts import PhoneAlerts
    monkeypatch.setattr(conftest.Node, "overrides", {"config": str(tmp_path / "none.json")})
    n = PhoneAlerts()
    assert n.n is None and n.subs == {}
