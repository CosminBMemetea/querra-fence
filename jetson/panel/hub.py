"""QUERRA device hub: the single owner of both cameras, plus shared GPS (gpsd) and radar (ld2450-radar) readers.

- Live view: 640 px JPEG frames at ~10 fps per camera, produced only while someone watches.
- Field mode consumes the USB camera through a local QFC1 stream (127.0.0.1:5602, the same protocol as the
  simulator stream), with the GPS fix in each frame header, so nobody else opens the camera or the GPS port.
- Cameras open on demand and close 20 s after the last viewer or consumer leaves.
"""
import json, math, os, socket, struct, threading, time, urllib.request
import cv2
import numpy as np
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)
USB_DEV = "/dev/video-uvc-rgb"


class Camera:
    IDLE_S = 20

    def __init__(self, name, pipeline, live_fps=10, allowed=lambda: (True, "")):
        self.name, self.pipeline_text, self.live_fps, self.allowed = name, pipeline, live_fps, allowed
        self.cond = threading.Condition()
        self.live = None; self.live_seq = 0; self.live_t = 0.0
        self.full = None; self.full_seq = 0; self.full_t = 0.0
        self.state, self.error = "off", None
        self.demand_view = 0.0; self.demand_full = 0.0
        self.pipe = None; self.fps = 0.0; self._n = 0; self._t0 = time.monotonic()
        self.width = self.height = None
        threading.Thread(target=self._manage, daemon=True, name=f"cam-{name}").start()

    # --- demand -------------------------------------------------------------
    def want_view(self): self.demand_view = time.monotonic()
    def want_full(self): self.demand_full = time.monotonic()
    def wanted(self): return time.monotonic() - max(self.demand_view, self.demand_full) < self.IDLE_S
    def viewing(self): return time.monotonic() - self.demand_view < 3

    def _manage(self):
        while True:
            ok, why = self.allowed()
            if self.pipe is None and self.wanted():
                if ok:
                    self._start()
                else:
                    self.state, self.error = "blocked", why
            elif self.pipe is not None and (not self.wanted() or not ok):
                self._stop("off" if ok else "blocked", None if ok else why)
            if self.pipe is not None:
                bus = self.pipe.get_bus()
                msg = bus.timed_pop_filtered(0, Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if msg:
                    err = msg.parse_error()[0].message if msg.type == Gst.MessageType.ERROR else "end of stream"
                    self._stop("error", err); time.sleep(3)
                elif self.state == "starting" and time.monotonic() - self._started > 12:
                    self._stop("error", "no frames from the camera"); time.sleep(3)
            if not self.wanted() and self.pipe is None and self.state not in ("error", "missing", "blocked"):
                self.state = "off"
            time.sleep(0.25)

    def _start(self):
        try:
            self.pipe = Gst.parse_launch(self.pipeline_text)
            sink = self.pipe.get_by_name("s")
            sink.connect("new-sample", self._on_sample)
            self.state, self.error, self._started = "starting", None, time.monotonic()
            self.pipe.set_state(Gst.State.PLAYING)
        except Exception as e:  # noqa: BLE001
            self.pipe = None; self.state, self.error = "error", str(e)

    def _stop(self, state, error=None):
        p, self.pipe = self.pipe, None
        if p is not None:
            p.set_state(Gst.State.NULL)
        self.state, self.error = state, error
        self.fps = 0.0

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer(); caps = sample.get_caps().get_structure(0)
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            self.width, self.height = caps.get_value("width"), caps.get_value("height")
            self.handle(bytes(info.data) if self.raw_jpeg else np.frombuffer(info.data, np.uint8).copy(), caps)
        finally:
            buf.unmap(info)
        if self.state == "starting":
            self.state = "live"
        self._n += 1
        now = time.monotonic()
        if now - self._t0 >= 2:
            self.fps = round(self._n / (now - self._t0), 1); self._n = 0; self._t0 = now
        return Gst.FlowReturn.OK

    def _publish_live(self, jpeg):
        with self.cond:
            self.live = jpeg; self.live_seq += 1; self.live_t = time.time(); self.cond.notify_all()

    def live_due(self):
        return self.viewing() and time.monotonic() - getattr(self, "_last_live", 0) >= 1.0 / self.live_fps

    def status(self):
        return {"state": self.state, "error": self.error, "fps": self.fps, "width": self.width, "height": self.height,
                "viewers": self.viewing(), "consumer": time.monotonic() - self.demand_full < 3}


class UsbCamera(Camera):
    """Arducam USB: MJPEG 1280x720 straight from the camera (no decode), downscaled only for live view."""
    raw_jpeg = True

    def __init__(self, **kw):
        super().__init__("usb", f"v4l2src device={USB_DEV} io-mode=2 ! image/jpeg,width=1280,height=720,framerate=30/1 "
                         "! appsink name=s emit-signals=true max-buffers=1 drop=true sync=false", **kw)

    def _start(self):
        if not os.path.exists(USB_DEV):
            self.state, self.error = "missing", f"{USB_DEV} not found"; return
        os.system(f"v4l2-ctl -d {USB_DEV} --set-ctrl=exposure_dynamic_framerate=0 >/dev/null 2>&1")
        super()._start()

    def handle(self, jpeg, caps):
        with self.cond:
            self.full = jpeg; self.full_seq += 1; self.full_t = time.time(); self.cond.notify_all()
        if self.live_due():
            self._last_live = time.monotonic()
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
            if img is not None:
                self._publish_live(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])[1].tobytes())


class CsiCamera(Camera):
    """IMX219 on CSI through Argus: hardware scaling to 640x360, white balance corrected in software."""
    raw_jpeg = False

    def __init__(self, wb="gray", **kw):
        self.wb = wb; self.gains = np.array([1.0, 1.0, 1.0], np.float32)
        super().__init__("csi", "nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1,format=NV12 "
                         "! nvvidconv ! video/x-raw,width=640,height=360,format=BGRx "
                         "! appsink name=s emit-signals=true max-buffers=1 drop=true sync=false", **kw)

    def handle(self, arr, caps):
        if not self.live_due():
            return
        self._last_live = time.monotonic()
        img = arr.reshape(caps.get_value("height"), caps.get_value("width"), 4)[:, :, :3]
        if self.wb == "gray":
            # Grey-world white balance with clamped, smoothed gains: removes the IMX219 magenta cast
            # (no ISP tuning file installed for this sensor).
            m = img[::8, ::8].reshape(-1, 3).astype(np.float32).mean(0) + 1e-3
            target = np.clip(m[1] / m, 0.5, 2.0); target[1] = 1.0
            self.gains = 0.85 * self.gains + 0.15 * target
            img = cv2.transform(img, np.diag(self.gains).astype(np.float32))
        else:
            img = np.ascontiguousarray(img)
        self._publish_live(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])[1].tobytes())


def ecef_to_latlon(x, y, z):
    """WGS-84 ECEF (m) to geodetic latitude and longitude (degrees), Bowring's formula (sub-metre near the ground)."""
    a, e2 = 6378137.0, 6.69437999014e-3
    b = a * math.sqrt(1 - e2); ep2 = (a * a - b * b) / (b * b)
    p = math.hypot(x, y); th = math.atan2(z * a, p * b)
    lat = math.atan2(z + ep2 * b * math.sin(th) ** 3, p - e2 * a * math.cos(th) ** 3)
    return math.degrees(lat), math.degrees(math.atan2(y, x))


def latlon_wrong(tpv):
    """True when a TPV with a fix has lat/lon that disagree with its own ECEF position (more than 50 m).

    gpsd 3.22 asks a u-blox 7 (PROTVER 14) only for NAV-SOL, which carries ECEF, and does not convert it: TPV then
    reports a 3D fix at lat 0, lon 0 (or the last lat/lon it saw). The ECEF fields stay right."""
    e = [tpv.get(k) for k in ("ecefx", "ecefy", "ecefz")]
    if (tpv.get("mode") or 0) < 2 or None in e:
        return False
    if tpv.get("lat") is None or tpv.get("lon") is None:
        return True
    lat, lon = ecef_to_latlon(*e)
    dn = math.radians(lat - tpv["lat"]) * 6371000.0
    de = math.radians(lon - tpv["lon"]) * 6371000.0 * math.cos(math.radians(lat))
    return math.hypot(dn, de) > 50.0


def ubx_frame(cls, mid, payload):
    body = bytes([cls, mid, len(payload) & 255, len(payload) >> 8]) + bytes(payload)
    a = b = 0
    for x in body:
        a = (a + x) & 255; b = (b + a) & 255
    return b"\xb5\x62" + body + bytes([a, b])


UBX_NAV_POSLLH_ON = ubx_frame(0x06, 0x01, [0x01, 0x02, 1]).hex()   # CFG-MSG: NAV-POSLLH once per fix, current port


class Gps:
    """One gpsd client (gpsd owns the u-blox port); publishes the latest fix.

    With a u-blox 7 under gpsd 3.22 the receiver must also send NAV-POSLLH, or gpsd reports lat 0, lon 0 under a 3D
    fix. The receiver keeps that setting only in RAM, so whenever the hub sees it (latlon_wrong), it asks gpsd to turn
    NAV-POSLLH back on (at most every 30 s) and reports no position until gpsd's lat/lon agree with ECEF again."""

    def __init__(self, host="127.0.0.1", port=2947):
        self.host, self.port = host, port
        self.tpv, self.sky, self.connected, self.error = {}, {}, False, None
        self.last_fix_mono = None; self.device = None; self.driver = None; self.healed_mono = None
        threading.Thread(target=self._run, daemon=True, name="gps").start()

    def _heal(self, s, path):
        now = time.monotonic()
        if self.driver != "u-blox" or not path or (self.healed_mono is not None and now - self.healed_mono < 30):
            return
        self.healed_mono = now
        s.sendall(("?DEVICE=" + json.dumps({"path": path, "hexdata": UBX_NAV_POSLLH_ON}) + ";\n").encode())
        print(f"gps: lat/lon disagree with ECEF on {path}; turned NAV-POSLLH back on", flush=True)

    def _run(self):
        while True:
            try:
                with socket.create_connection((self.host, self.port), timeout=5) as s:
                    s.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    self.connected, self.error = True, None
                    f = s.makefile("r", encoding="utf-8", errors="replace")
                    for line in f:
                        try:
                            m = json.loads(line)
                        except ValueError:
                            continue
                        c = m.get("class")
                        if c == "TPV":
                            if latlon_wrong(m):
                                self._heal(s, m.get("device") or self.device)
                                m = dict(m, lat=None, lon=None, alt=None, altHAE=None, altMSL=None)
                            self.tpv = m; self.device = m.get("device")
                            if (m.get("mode") or 0) >= 2 and m.get("lat") is not None:
                                self.last_fix_mono = time.monotonic()
                        elif c == "SKY":
                            if "satellites" in m or "hdop" in m:
                                self.sky = m
                        elif c == "DEVICES":
                            devs = m.get("devices") or []
                            self.device = devs[0].get("path") if devs else None
                            self.driver = devs[0].get("driver") if devs else None
                        elif c == "DEVICE" and m.get("driver"):
                            self.driver = m["driver"]
            except OSError as e:
                self.error = str(e)
            self.connected = False
            time.sleep(3)

    def state(self):
        t, k = self.tpv, self.sky
        sats = k.get("satellites") or []
        used = k.get("uSat", sum(1 for x in sats if x.get("used")))
        age = None if self.last_fix_mono is None else round(time.monotonic() - self.last_fix_mono, 1)
        mode = t.get("mode") or 0
        fresh = age is not None and age < 5
        return {"connected": self.connected, "device": self.device, "error": self.error,
                "mode": mode if fresh or mode < 2 else 0, "fix": {0: "none", 1: "none", 2: "2D", 3: "3D"}.get(mode if fresh else 0, "none"),
                "lat": t.get("lat"), "lon": t.get("lon"), "alt_m": t.get("altMSL", t.get("alt")), "speed_ms": t.get("speed"),
                "track_deg": t.get("track"), "time": t.get("time"), "eph_m": t.get("eph"),
                "sats_used": used, "sats_seen": k.get("nSat", len(sats)), "hdop": k.get("hdop"), "fix_age_s": age}

    def telemetry(self):
        """Header block for field mode (querra-scout SimTelemetryGPS: lat/lon valid while age_s <= 5)."""
        s = self.state()
        ok = s["mode"] >= 2 and s["lat"] is not None
        return {"lat": s["lat"] if ok else None, "lon": s["lon"] if ok else None, "alt_m": s["alt_m"], "speed_ms": s["speed_ms"],
                "heading_deg": s["track_deg"], "age_s": s["fix_age_s"] if s["fix_age_s"] is not None else 99,
                "phase": "field", "mode": s["fix"], "sats_used": s["sats_used"], "hdop": s["hdop"], "source": "gpsd"}


class Radar:
    """LD2450 through the ld2450-radar service (it owns /dev/ttyUSB0); cached ~10 Hz."""

    def __init__(self, url="http://127.0.0.1:8077/state"):
        self.url, self._t, self._v = url, 0.0, None
        self.lock = threading.Lock()

    def state(self):
        with self.lock:
            if time.monotonic() - self._t > 0.09:
                try:
                    with urllib.request.urlopen(self.url, timeout=0.8) as r:
                        v = json.loads(r.read())
                    v["service"] = True
                except Exception as e:  # noqa: BLE001
                    v = {"service": False, "connected": False, "error": f"radar service not reachable ({e.__class__.__name__})", "targets": []}
                self._v, self._t = v, time.monotonic()
            return self._v


class FieldFeed:
    """QFC1 frames (USB camera, full size) for querra-scout field mode on 127.0.0.1:<port>, GPS in the header."""

    def __init__(self, cam, gps, port=5602, max_fps=15):
        self.cam, self.gps, self.port, self.max_fps, self.clients = cam, gps, port, max_fps, 0
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port)); srv.listen(4); self.srv = srv
        threading.Thread(target=self._accept, daemon=True, name="feed").start()

    def _accept(self):
        while True:
            c, _ = self.srv.accept()
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        self.clients += 1
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        seq, last = -1, 0.0
        try:
            while True:
                self.cam.want_full()
                with self.cam.cond:
                    self.cam.cond.wait_for(lambda: self.cam.full_seq != seq, timeout=1.0)
                    jpeg, seq2, t = self.cam.full, self.cam.full_seq, self.cam.full_t
                if jpeg is None or seq2 == seq:
                    continue
                wait = 1.0 / self.max_fps - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait); continue
                seq, last = seq2, time.monotonic()
                h = json.dumps({"seq": seq, "width": self.cam.width, "height": self.cam.height, "t_capture": t,
                                "t_send": time.time(), "sim_time_s": None, "source": "querra-panel-hub:usb",
                                "telemetry": self.gps.telemetry()}).encode()
                c.sendall(b"QFC1" + struct.pack(">II", len(h), len(jpeg)) + h + jpeg)
        except OSError:
            pass
        finally:
            self.clients -= 1
            c.close()
