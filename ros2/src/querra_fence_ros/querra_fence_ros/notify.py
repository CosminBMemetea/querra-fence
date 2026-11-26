"""Phone alerts: a confirmed fence fault as a push notification, with its photo and a map link.

Backends, set up with tools/notify.py and kept in a JSON file only you can read (never in git):
  ~/.config/querra/notify.json   (or $QUERRA_NOTIFY; in the ROS 2 container /etc/querra/notify.json, mounted by ros.sh)

  {"ntfy": {"topic": "querra-...", "server": "https://ntfy.sh", "token": null},
   "telegram": {"bot_token": "...", "chat_id": "...", "location": true},
   "burst": 5, "refill_s": 300}

Either backend or both. ntfy needs no account: anyone who knows the topic can read it, so the topic is a long random
name. Telegram needs a bot (@BotFather) and sends the photo, then a map pin.

Used by the ROS 2 node phone_alerts (the drone's and the ground robot's /fence/alerts) and by tools/video_eval.py
--notify. Standard library only; OpenCV, where installed, draws the boxes on the photo.

Delivery runs on its own thread. `burst` messages go out at once, then one every `refill_s` seconds; alerts that wait
meanwhile go out together as one summary, so a storm of false alerts is a few messages, not fifty (the public
ntfy.sh allows about 250 a day). A failed send is retried for about an hour (no network in the field, a server error,
a rate limit); a backend that refuses (a wrong token, an unknown chat) is reported and not retried. Errors name the
backend, never the URL: the bot token is in Telegram's URLs and the topic in ntfy's.
"""
import base64
import json
import math
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

LABELS = {"wire_break": "Broken wire", "fallen_post": "Fallen post", "branch": "Branch on the wires"}
CONFIG_PATHS = ("~/.config/querra/notify.json", "/etc/querra/notify.json")
RETRY_S = (10, 30, 60, 120, 300, 600, 900, 1500)          # about an hour in all


# ------------------------------------------------------------------ configuration and text

def config_path(path=None):
    """The config file in use: the given path, $QUERRA_NOTIFY, or the first of CONFIG_PATHS that exists."""
    if path:
        return os.path.expanduser(path)
    if os.environ.get("QUERRA_NOTIFY"):
        return os.path.expanduser(os.environ["QUERRA_NOTIFY"])
    found = [os.path.expanduser(p) for p in CONFIG_PATHS if os.path.exists(os.path.expanduser(p))]
    return found[0] if found else os.path.expanduser(CONFIG_PATHS[0])


def load_config(path=None):
    p = config_path(path)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def map_url(lat, lon):
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return "https://maps.google.com/?q=%.6f,%.6f" % (lat, lon)


def describe(a):
    """(title, text, map link) of one alert: a dict with class and any of source, id, conf, frames, lat, lon, time
    (epoch s) and note (e.g. where in a video)."""
    label = LABELS.get(a.get("class"), a.get("class") or "Fence fault")
    title = label + (" · " + a["source"] if a.get("source") else "")
    bits = (["Alert %s" % a["id"]] if a.get("id") is not None else []) + \
           (["conf %.2f" % a["conf"]] if a.get("conf") is not None else []) + \
           (["%d frames" % a["frames"]] if a.get("frames") else [])
    when = time.strftime("%H:%M:%S", time.localtime(a.get("time") or time.time()))
    lines = [(", ".join(bits) + " at " if bits else "At ") + when]
    if a.get("note"):
        lines.append(a["note"])
    url = map_url(a.get("lat"), a.get("lon"))
    if url:
        lines.append("%.6f, %.6f" % (a["lat"], a["lon"]))
    return title, "\n".join(lines), url


def summarise(alerts, shown=10):
    """(title, text, map link) of several alerts sent together."""
    sources = sorted({a.get("source") for a in alerts if a.get("source")})
    title = "%d fence alerts" % len(alerts) + (" · " + ", ".join(sources) if sources else "")
    lines = []
    for a in alerts[:shown]:
        t, text, _ = describe(dict(a, source=None))
        lines.append("- %s: %s" % (t, text.replace("\n", ", ")))
    if len(alerts) > shown:
        lines.append("... and %d more" % (len(alerts) - shown))
    url = next((u for u in (map_url(a.get("lat"), a.get("lon")) for a in alerts) if u), None)
    return title, "\n".join(lines), url


def annotate(jpeg, boxes, highlight=None):
    """The photo with the fault boxes drawn, the alert's class thick. boxes: (class, conf, cx, cy, w, h) in pixels.
    Returns the JPEG unchanged without OpenCV or when it cannot be decoded."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return jpeg
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jpeg
    th = max(1, round(img.shape[1] / 640))
    for c, s, cx, cy, w, h in boxes:
        if c not in LABELS:
            continue
        on = c == highlight
        col = (40, 40, 255) if on else (0, 200, 255)
        x0, y0, x1, y1 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
        cv2.rectangle(img, (x0, y0), (x1, y1), col, (3 if on else 1) * th)
        cv2.putText(img, "%s %.2f" % (c, s), (x0, max(14 * th, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, col, th)
    ok, out = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out.tobytes() if ok else jpeg


# ------------------------------------------------------------------ backends

class SendError(Exception):
    def __init__(self, msg, retry=True, after=None):
        super().__init__(msg)
        self.retry, self.after = retry, after


def http(req, timeout):
    """Send a request; SendError says whether to retry. The message never holds the URL."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "replace")
        after = None
        try:
            after = float(e.headers.get("Retry-After") or json.loads(body).get("parameters", {}).get("retry_after"))
        except (TypeError, ValueError, AttributeError):
            pass
        try:
            detail = json.loads(body).get("description") or json.loads(body).get("error") or ""
        except (ValueError, AttributeError):
            detail = ""
        raise SendError(("HTTP %d %s" % (e.code, detail)).strip(), retry=e.code == 429 or e.code >= 500, after=after)
    except (urllib.error.URLError, OSError) as e:
        raise SendError("no connection (%s)" % type(getattr(e, "reason", e)).__name__)


class Ntfy:
    name = "ntfy"

    def __init__(self, topic, server="https://ntfy.sh", token=None, priority="high", timeout=20, **_):
        self.topic, self.server, self.token, self.priority, self.timeout = topic, server.rstrip("/"), token, priority, timeout

    def send(self, title, text, click=None, jpeg=None, lat=None, lon=None):
        # options as URL parameters: they carry UTF-8 and line breaks, which headers do not reliably
        q = {"title": title, "tags": "warning", "priority": self.priority}
        if click:
            q["click"] = click
        if jpeg:
            q.update(message=text, filename="alert.jpg")
        headers = {}
        if self.token:
            headers["Authorization"] = ("Basic " + base64.b64encode(self.token.encode()).decode()) if ":" in self.token \
                else "Bearer " + self.token
        url = "%s/%s?%s" % (self.server, urllib.parse.quote(self.topic, safe=""), urllib.parse.urlencode(q))
        http(urllib.request.Request(url, data=jpeg or text.encode("utf-8"), headers=headers,
                                    method="PUT" if jpeg else "POST"), self.timeout)


class Telegram:
    name = "telegram"

    def __init__(self, bot_token, chat_id, location=True, api="https://api.telegram.org", timeout=20, **_):
        self.token, self.chat, self.location, self.api, self.timeout = bot_token, str(chat_id), location, api.rstrip("/"), timeout

    def call(self, method, fields, photo=None):
        url = "%s/bot%s/%s" % (self.api, self.token, method)
        if photo is None:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        else:
            b = uuid.uuid4().hex
            parts = [("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8")
                     for k, v in fields.items()]
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"alert.jpg\"\r\n"
                          "Content-Type: image/jpeg\r\n\r\n" % b).encode() + photo + b"\r\n")
            parts.append(("--%s--\r\n" % b).encode())
            req = urllib.request.Request(url, data=b"".join(parts), headers={"Content-Type": "multipart/form-data; boundary=" + b})
        r = json.loads(http(req, self.timeout))
        if not r.get("ok"):
            raise SendError("Telegram: %s" % r.get("description"), retry=False)
        return r.get("result")

    def send(self, title, text, click=None, jpeg=None, lat=None, lon=None):
        msg = "⚠️ " + title + "\n" + text + ("\n" + click if click else "")
        if jpeg:
            self.call("sendPhoto", {"chat_id": self.chat, "caption": msg[:1024]}, jpeg)
        else:
            self.call("sendMessage", {"chat_id": self.chat, "text": msg[:4096], "disable_web_page_preview": "true"})
        if self.location and map_url(lat, lon):
            self.call("sendLocation", {"chat_id": self.chat, "latitude": "%.6f" % lat, "longitude": "%.6f" % lon})


def backends(cfg):
    out = []
    if (cfg or {}).get("ntfy", {}).get("topic"):
        out.append(Ntfy(**cfg["ntfy"]))
    t = (cfg or {}).get("telegram", {})
    if t.get("bot_token") and t.get("chat_id"):
        out.append(Telegram(**t))
    return out


# ------------------------------------------------------------------ delivery

class Limiter:
    """A token bucket: `burst` messages at once, then one every `refill_s` seconds."""

    def __init__(self, burst=5, refill_s=300.0):
        self.burst, self.refill = max(1, int(burst)), float(refill_s)
        self.tokens, self.t = float(self.burst), time.monotonic()

    def _now(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.t) / self.refill)
        self.t = now

    def wait_s(self):
        self._now()
        return 0.0 if self.tokens >= 1 else (1 - self.tokens) * self.refill

    def take(self):
        self._now()
        self.tokens -= 1


class Notifier:
    """Queues alerts and notes and delivers them to every backend on a background thread (see the module doc)."""

    def __init__(self, cfg, log=print, sends=None, retry_s=RETRY_S):
        cfg = cfg or {}
        self.backends = sends if sends is not None else backends(cfg)
        self.limiter = Limiter(cfg.get("burst", 5), cfg.get("refill_s", 300))
        self.log, self.retry = log, tuple(retry_s)
        self.sent, self.failed = [], []                    # (backend name, title), for the record and the tests
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="notify", daemon=True)
        self.thread.start()

    def alert(self, a, jpeg=None):
        self.q.put(("alert", a, jpeg))

    def note(self, title, text):
        self.q.put(("note", {"title": title, "text": text}, None))

    def close(self, timeout=120):
        """Send what is queued now, without waiting for the rate limit, and stop."""
        self.q.put(None)
        self.thread.join(timeout)

    def _run(self):
        stop = False
        while not stop:
            item = self.q.get()
            if item is None:
                break
            batch, deadline = [item], time.monotonic() + self.limiter.wait_s()
            while True:                                    # gather what arrives until a message may go out
                left = deadline - time.monotonic()
                try:
                    x = self.q.get(timeout=left) if left > 0 else self.q.get_nowait()
                except queue.Empty:
                    break
                if x is None:
                    stop = True
                    break
                batch.append(x)
            self.limiter.take()
            self._deliver(batch)

    def _deliver(self, batch):
        for _, n, _ in (b for b in batch if b[0] == "note"):
            self._send_all(n["title"], n["text"])
        alerts = [b for b in batch if b[0] == "alert"]
        if len(alerts) == 1:
            _, a, jpeg = alerts[0]
            title, text, url = describe(a)
            self._send_all(title, text, url, jpeg, a.get("lat"), a.get("lon"))
        elif alerts:
            title, text, url = summarise([a for _, a, _ in alerts])
            jpeg = next((j for _, _, j in reversed(alerts) if j), None)      # the newest photo
            first = next((a for _, a, _ in alerts if map_url(a.get("lat"), a.get("lon"))), {})
            self._send_all(title, text, url, jpeg, first.get("lat"), first.get("lon"))

    def _send_all(self, title, text, url=None, jpeg=None, lat=None, lon=None):
        for b in self.backends:
            for k in range(len(self.retry) + 1):
                try:
                    b.send(title, text, url, jpeg, lat, lon)
                    self.sent.append((b.name, title))
                    break
                except SendError as e:
                    if not e.retry or k == len(self.retry):
                        self.log("phone alert not sent by %s: %s" % (b.name, e))
                        self.failed.append((b.name, title))
                        break
                    wait = max(self.retry[k], e.after or 0)
                    if k == 0:
                        self.log("phone alert by %s failed (%s); retrying for up to %d min" % (b.name, e, sum(self.retry) // 60))
                    time.sleep(wait)
