"""Multi-frame GPS confirmation for fence faults (querra-scout).

A single frame never raises an alert. A fault class becomes an alert only when at least N of the last M
detector frames saw that class at the same ground spot (within RADIUS metres). Each box is placed on the ground
with a flat-ground pinhole model: drone GPS + altitude + heading, camera pitched 55 degrees down, fx 465.7 px at
640x400. Sightings within merge_m (10 m) of an existing alert update it. If heading or altitude are missing it falls back to the drone position. One spot alerts once; later
sightings only update its count and best confidence.

    from querra_scout.confirm import AlertConfirmer
    c = AlertConfirmer(n=5, m=8, radius_m=5.0, conf=0.7)
    for alert in c.update(frame_dets, lat, lon, alt_m, heading_deg): ...

Offline: python3 confirm.py detections.jsonl [--n 5 --m 8 --radius 5 --conf 0.7]
"""
import argparse, collections, json, math

FAULTS = ("wire_break", "fallen_post", "branch")
M_PER_DEG_LAT = 111132.0


def ground_point(lat, lon, alt_m, heading_deg, box, img_w=640, img_h=400, fx=465.7, pitch_deg=55.0):
    """Lat/lon of the ground under the box's bottom-centre pixel (flat ground, camera looking forward-down)."""
    if lat is None or lon is None:
        return None
    if alt_m is None or heading_deg is None or alt_m < 1.0:
        return lat, lon
    x1, y1, x2, y2 = box
    u, v = (x1 + x2) / 2.0, max(y1, y2) * 0.5 + (y1 + y2) * 0.25  # between centre and bottom: the object's foot
    x, y = (u - img_w / 2.0) / fx, (v - img_h / 2.0) / fx
    th = math.radians(pitch_deg)
    fwd, right, down = math.cos(th) - y * math.sin(th), x, math.sin(th) + y * math.cos(th)
    if down <= 0.05:                       # at or above the horizon: no ground hit
        return lat, lon
    t = alt_m / down
    f, r = min(t * fwd, 80.0), t * right
    psi = math.radians(heading_deg)
    north, east = f * math.cos(psi) - r * math.sin(psi), f * math.sin(psi) + r * math.cos(psi)
    return lat + north / M_PER_DEG_LAT, lon + east / (M_PER_DEG_LAT * math.cos(math.radians(lat)))


def dist_m(a, b):
    return math.hypot((a[0] - b[0]) * M_PER_DEG_LAT, (a[1] - b[1]) * M_PER_DEG_LAT * math.cos(math.radians(a[0])))


class AlertConfirmer:
    def __init__(self, n=5, m=8, radius_m=5.0, conf=0.7, classes=FAULTS, merge_m=10.0):
        assert 1 <= n <= m
        self.n, self.m, self.radius, self.conf, self.classes = n, m, radius_m, conf, set(classes)
        self.merge = max(merge_m, radius_m)  # a new sighting this close to an existing alert updates it, no new alert
        self.window = collections.deque(maxlen=m)   # per frame: {class: [(lat, lon, conf)]}
        self.alerts = []                              # confirmed spots

    def update(self, detections, lat, lon, alt_m=None, heading_deg=None, meta=None):
        """Feed one detector frame. Returns the list of NEW alerts confirmed by this frame."""
        frame = collections.defaultdict(list)
        for d in detections or ():
            if d.get("class") in self.classes and d.get("conf", 0) >= self.conf:
                p = ground_point(lat, lon, alt_m, heading_deg, d.get("box_xyxy") or d.get("box"))
                if p:
                    frame[d["class"]].append((p[0], p[1], d["conf"]))
        self.window.append(frame)
        new = []
        for cls, pts in frame.items():
            for la, lo, cf in pts:
                old = next((a for a in self.alerts if a["class"] == cls and dist_m((la, lo), (a["lat"], a["lon"])) <= self.merge), None)
                if old:
                    old["sightings"] += 1
                    old["max_conf"] = max(old["max_conf"], round(cf, 3))
                    continue
                support = [next(((q[0], q[1]) for q in f.get(cls, ()) if dist_m((la, lo), q) <= self.radius), None)
                           for f in self.window]
                hits = [s for s in support if s]
                if len(hits) >= self.n:
                    a = dict(cls=cls, lat=round(sum(h[0] for h in hits) / len(hits), 7),
                             lon=round(sum(h[1] for h in hits) / len(hits), 7), frames=len(hits),
                             max_conf=round(cf, 3), sightings=len(hits), **(meta or {}))
                    a["class"] = a.pop("cls")
                    self.alerts.append(a)
                    new.append(a)
        return new


def main():
    ap = argparse.ArgumentParser(description="Replay detections.jsonl through the multi-frame confirmation")
    ap.add_argument("jsonl")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--m", type=int, default=8)
    ap.add_argument("--radius", type=float, default=5.0)
    ap.add_argument("--conf", type=float, default=0.7)
    ap.add_argument("--merge", type=float, default=10.0)
    ap.add_argument("--out", help="write alerts.jsonl here")
    a = ap.parse_args()
    c = AlertConfirmer(a.n, a.m, a.radius, a.conf, merge_m=a.merge)
    out = open(a.out, "w") if a.out else None
    for line in open(a.jsonl):
        r = json.loads(line)
        g = r.get("gps") or {}
        tl = r.get("telemetry") or {}
        for al in c.update(r.get("detections"), g.get("latitude", tl.get("lat")), g.get("longitude", tl.get("lon")),
                           r.get("altitude_m", tl.get("alt_m")), r.get("heading_deg", tl.get("heading_deg")),
                           dict(frame_index=r.get("frame_index"), sim_time_s=r.get("sim_time_s"))):
            if out:
                out.write(json.dumps(al) + "\n")
    for al in c.alerts:
        print(json.dumps(al))
    print("alerts:", len(c.alerts), collections.Counter(x["class"] for x in c.alerts))


if __name__ == "__main__":
    main()
