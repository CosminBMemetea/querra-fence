#!/usr/bin/env python3
"""LD2450 radar: live web view.

Reads a HiLink LD2450 (24 GHz mmWave, up to 3 targets) through a USB-serial adapter (CH340)
and serves a live radar page to any browser on the network.

    python3 server.py                          # auto-detects the CH340, http://<jetson>:8077
    python3 server.py --serial /dev/ttyUSB0 --http 8077
    python3 server.py --demo                   # synthetic targets, no sensor needed

Endpoints
    /              the page
    /events        Server-Sent Events, one JSON message per radar frame (~10 Hz)
    /state         the latest message as JSON
    POST /mode?set=multi|single   switch the sensor's tracking mode

Needs Python 3.8+ and pyserial (preinstalled on JetPack). Unplugging and replugging the adapter is handled.
"""
import argparse
import collections
import glob
import json
import math
import os
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))

# Report frame: AA FF 03 00 | 3 x [x, y, speed, resolution] (int16 LE each) | 55 CC  = 30 bytes
REPORT_HEAD, REPORT_TAIL, REPORT_LEN = b"\xaa\xff\x03\x00", b"\x55\xcc", 30
# Command / ACK frame: FD FC FB FA | length (2) | command word (2) | value | 04 03 02 01
CMD_HEAD, CMD_TAIL = b"\xfd\xfc\xfb\xfa", b"\x04\x03\x02\x01"
CMD_ENABLE_CFG, CMD_END_CFG = 0x00FF, 0x00FE
CMD_SINGLE, CMD_MULTI, CMD_QUERY_MODE, CMD_FIRMWARE = 0x0080, 0x0090, 0x0091, 0x00A0


def signed(raw):
    """LD2450 sign convention: top bit set = positive, value in the low 15 bits."""
    return (raw & 0x7FFF) if raw & 0x8000 else -raw


def parse_report(frame):
    """3 slots: dict(x, y mm; v cm/s; res mm) or None for an empty slot."""
    out = []
    for k in range(3):
        b = frame[4 + 8 * k: 12 + 8 * k]
        if b == b"\x00" * 8:
            out.append(None)
            continue
        x, y, v, r = (int.from_bytes(b[j:j + 2], "little") for j in (0, 2, 4, 6))
        out.append(dict(x=signed(x), y=signed(y), v=signed(v), res=r))
    return out


class Hub:
    """Latest state + fan-out to the browsers."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.msg = None
        self.times = collections.deque(maxlen=40)
        # config: True = the sensor answers commands; False = it only streams (its RX is not wired)
        self.status = dict(host=socket.gethostname(), connected=False, port=None, firmware=None, mode=None,
                           config=None, fps=0.0, frames=0, bad=0, demo=False, error=None)

    def frame(self, targets):
        now = time.time()
        self.times.append(now)
        st = self.status
        st["frames"] += 1
        st["error"] = None
        if len(self.times) > 1 and now > self.times[0]:
            st["fps"] = round((len(self.times) - 1) / (now - self.times[0]), 1)
        self.publish(targets)

    def idle(self, error):
        self.times.clear()
        self.status.update(fps=0.0, error=error)
        self.publish()

    def publish(self, targets=None):
        msg = dict(self.status, t=round(time.time(), 3), targets=targets or [None, None, None])
        with self.cond:
            self.seq += 1
            msg["seq"] = self.seq
            self.msg = json.dumps(msg, separators=(",", ":"))
            self.cond.notify_all()

    def wait(self, seq, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != seq, timeout)
            return self.seq, self.msg


class Sensor(threading.Thread):
    def __init__(self, hub, port, baud):
        super().__init__(daemon=True)
        self.hub, self.port_arg, self.baud = hub, port, baud
        self.commands = queue.Queue()
        self.ser = None

    def find_port(self):
        if self.port_arg:
            return self.port_arg if os.path.exists(self.port_arg) else None
        for pattern in ("/dev/serial/by-id/*1a86*", "/dev/ttyUSB*", "/dev/cu.wchusbserial*", "/dev/cu.usbserial*"):
            hits = sorted(glob.glob(pattern))
            if hits:
                return hits[0]
        return None

    def run(self):
        import serial  # pyserial; imported here so --demo works without it

        st, last_log = self.hub.status, None
        while True:
            port = self.find_port()
            if not port:
                st.update(connected=False, port=None)
                self.hub.idle("no USB-serial adapter found")
                if last_log != "missing":
                    print("[radar] waiting for the USB-serial adapter...", flush=True)
                    last_log = "missing"
                time.sleep(1)
                continue
            try:
                with serial.Serial(port, self.baud, timeout=0.1) as s:
                    self.ser = s
                    st.update(connected=True, port=os.path.realpath(port), error=None)
                    print("[radar] reading %s at %d baud" % (st["port"], self.baud), flush=True)
                    last_log = "open"
                    self.hub.publish()
                    self.query_info()
                    self.read_loop()
            except Exception as e:  # unplugged, permission denied, ...
                st.update(connected=False)
                self.hub.idle(str(e)[:160])
                if last_log != "error":
                    print("[radar] serial: %s" % e, flush=True)
                    last_log = "error"
                time.sleep(1)

    def read_loop(self):
        s, st, buf = self.ser, self.hub.status, bytearray()
        last_frame = last_idle = time.time()
        while True:
            if not self.commands.empty():
                self.set_mode(self.commands.get())
                buf.clear()
                last_frame = time.time()
            buf += s.read(512)
            while True:
                i = buf.find(REPORT_HEAD)
                if i < 0:
                    del buf[:max(0, len(buf) - 3)]
                    break
                if len(buf) - i < REPORT_LEN:
                    del buf[:i]
                    break
                frame = bytes(buf[i:i + REPORT_LEN])
                if frame[-2:] == REPORT_TAIL:
                    del buf[:i + REPORT_LEN]
                    last_frame = time.time()
                    self.hub.frame(parse_report(frame))
                else:
                    st["bad"] += 1
                    del buf[:i + 1]
            now = time.time()
            if now - last_frame > 1.5 and now - last_idle > 1.0:
                last_idle = now
                self.hub.idle("adapter connected but no data from the LD2450 (check TX->RX, GND, 5 V)")

    # --- configuration commands -------------------------------------------------------------
    def command(self, word, value=b"", wait=1.0):
        """Send one command, return the ACK payload (status + data) or None."""
        s = self.ser
        body = word.to_bytes(2, "little") + value
        s.write(CMD_HEAD + len(body).to_bytes(2, "little") + body + CMD_TAIL)
        s.flush()
        want = (word | 0x0100).to_bytes(2, "little")
        buf, t0 = bytearray(), time.time()
        while time.time() - t0 < wait:
            buf += s.read(256)
            i = buf.find(CMD_HEAD)
            while 0 <= i and len(buf) >= i + 8:
                end = i + 6 + int.from_bytes(buf[i + 4:i + 6], "little") + 4
                if len(buf) < end:
                    break
                if buf[i + 6:i + 8] == want and buf[end - 4:end] == CMD_TAIL:
                    return bytes(buf[i + 8:end - 4])
                i = buf.find(CMD_HEAD, i + 1)
        return None

    def in_config(self, fn):
        ack = self.command(CMD_ENABLE_CFG, b"\x01\x00") or self.command(CMD_ENABLE_CFG, b"\x01\x00")
        if not ack or ack[:2] != b"\x00\x00":
            return False
        try:
            fn()
        finally:
            self.command(CMD_END_CFG)
            self.ser.reset_input_buffer()
        return True

    def query_info(self):
        st = self.hub.status

        def ask():
            fw = self.command(CMD_FIRMWARE)
            if fw and len(fw) >= 10 and fw[:2] == b"\x00\x00":
                st["firmware"] = "V%d.%02X.%08X" % (fw[5], fw[4], int.from_bytes(fw[6:10], "little"))
            m = self.command(CMD_QUERY_MODE)
            if m and len(m) >= 4 and m[:2] == b"\x00\x00":
                st["mode"] = {1: "single", 2: "multi"}.get(int.from_bytes(m[2:4], "little"))

        st["config"] = self.in_config(ask)
        self.hub.publish()
        if not st["config"]:
            print("[radar] the sensor did not answer configuration commands (its RX may not be wired); "
                  "reading only", flush=True)
        else:
            print("[radar] firmware %s, %s-target mode" % (st["firmware"], st["mode"]), flush=True)

    def set_mode(self, mode):
        st = self.hub.status

        def apply():
            ack = self.command(CMD_SINGLE if mode == "single" else CMD_MULTI)
            if ack and ack[:2] == b"\x00\x00":
                st["mode"] = mode

        self.in_config(apply)
        print("[radar] tracking mode: %s" % st["mode"], flush=True)
        self.hub.publish()


def demo(hub):
    """Three synthetic people: one strolling, one walking through, one standing."""
    hub.status.update(connected=True, port="demo", firmware="demo", mode="multi", config=True, demo=True)
    t0, last_d = time.time(), [None, None, None]
    while True:
        t = time.time() - t0
        pos = [(1600 * math.sin(t * 0.31), 3200 + 1300 * math.sin(t * 0.53))]
        ph = (t % 26) / 26
        pos.append((-2600 + 5000 * ph / 0.6, 1200 + 2600 * math.sin(math.pi * ph / 0.6)) if ph < 0.6 else None)
        pos.append((-700 + 40 * math.sin(t * 2.1), 1400 + 30 * math.cos(t * 1.7)) if (t % 40) > 12 else None)
        targets = []
        for k, p in enumerate(pos):
            if p is None:
                targets.append(None)
                last_d[k] = None
                continue
            d = math.hypot(*p)
            v = 0 if last_d[k] is None else round((d - last_d[k]) / 0.1 / 10)
            last_d[k] = d
            targets.append(dict(x=round(p[0]), y=round(p[1]), v=v, res=320))
        hub.frame(targets)
        time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    hub = None
    sensor = None

    def send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self.send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/events":
            self.events()
        elif path == "/state":
            self.send(200, self.hub.msg or "{}", "application/json")
        elif path == "/health":
            self.send(200, "ok", "text/plain")
        else:
            self.send(404, "not found", "text/plain")

    def do_POST(self):
        url = urlparse(self.path)
        mode = parse_qs(url.query).get("set", [""])[0]
        if url.path == "/mode" and mode in ("single", "multi"):
            if self.sensor is None:
                self.send(409, '{"ok":false,"error":"demo mode"}', "application/json")
            else:
                self.sensor.commands.put(mode)
                self.send(202, '{"ok":true}', "application/json")
        else:
            self.send(400, '{"ok":false}', "application/json")

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        seq = -1
        try:
            while True:
                new, msg = self.hub.wait(seq, 15)
                if new == seq or msg is None:
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(b"data: " + msg.encode("utf-8") + b"\n\n")
                seq = new
                self.wfile.flush()
        except OSError:
            pass  # browser closed the page

    def log_message(self, *args):
        pass


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="LD2450 live radar web view")
    ap.add_argument("--serial", help="serial port (default: auto-detect the CH340 / first ttyUSB)")
    ap.add_argument("--baud", type=int, default=256000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--http", type=int, default=8077)
    ap.add_argument("--demo", action="store_true", help="synthetic targets, no sensor")
    a = ap.parse_args()

    hub = Hub()
    sensor = None
    if a.demo:
        threading.Thread(target=demo, args=(hub,), daemon=True).start()
    else:
        sensor = Sensor(hub, a.serial, a.baud)
        sensor.start()
    Handler.hub, Handler.sensor = hub, sensor
    server = ThreadingHTTPServer((a.host, a.http), Handler)
    shown = lan_ip() if a.host == "0.0.0.0" else a.host
    print("[radar] open http://%s:%d" % (shown, a.http), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
