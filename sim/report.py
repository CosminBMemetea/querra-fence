"""Raport HTML (hartă SVG + profil EM) din datele misiunii."""
import html
import json

TYPE_RO = {"wire_break": "Sârmă ruptă", "post_down": "Stâlp căzut", "branch_short": "Creangă pe gard"}
PRIO = {"wire_break": ("Urgent", "crit"), "post_down": ("Urgent", "crit"), "branch_short": ("Azi", "warn")}


def _map_svg(d):
    pts = [tuple(p) for p in d["fence_polygon"]] + [tuple(p) for p in d["track"]] + [(0, 0)]
    pts += [(a["x"], a["y"]) for a in d["escaped_animals"]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 14
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    W = 760
    k = W / (x1 - x0)
    H = (y1 - y0) * k

    def P(x, y):
        return "%.1f,%.1f" % ((x - x0) * k, (y1 - y) * k)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Harta pășunii cu defecte și animale">' % (W, H)]
    out.append('<rect width="100%" height="100%" fill="#16241b"/>')
    out.append('<polygon points="%s" fill="#24402a" stroke="none"/>' % " ".join(P(*p) for p in d["fence_polygon"]))
    posts = d["posts"]
    out.append('<polyline points="%s" fill="none" stroke="#f2c230" stroke-width="2"/>' % " ".join(P(*p) for p in posts))
    if d["track"]:
        out.append('<polyline points="%s" fill="none" stroke="#7fd3ff" stroke-width="1.6" stroke-dasharray="5 4" opacity=".85"/>' % " ".join(P(*p) for p in d["track"]))
    out.append('<g transform="translate(%s)"><circle r="7" fill="#0e1c20" stroke="#e6efe9"/><text y="4" text-anchor="middle" font-size="10" fill="#e6efe9" font-weight="700">H</text></g>' % P(0, 0))
    for f in d["faults"]:
        out.append('<g transform="translate(%s)"><circle r="10" fill="none" stroke="#f09a3a" stroke-width="2.5"/><circle r="3" fill="#f09a3a"/>'
                   '<text x="14" y="4" font-size="12" fill="#f09a3a" font-weight="600">%s %s</text></g>' % (P(f["x"], f["y"]), f["id"], html.escape(TYPE_RO.get(f["type"], ""))))
    for a in d["escaped_animals"]:
        out.append('<g transform="translate(%s)"><circle r="6" fill="#ff5b4f"/><text x="10" y="4" font-size="11" fill="#ff8a80">%s</text></g>' % (P(a["x"], a["y"]), a["id"]))
    out.append("</svg>")
    return "\n".join(out)


def _em_svg(d, length):
    prof = d["em_profile"]
    W, H, L, B = 760, 170, 34, 22
    vmax = 10.0

    def X(s):
        return L + (W - L - 8) * s / max(1.0, length)

    def Y(v):
        return 8 + (H - B - 8) * (1 - v / vmax)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Tensiunea gardului măsurată de-a lungul lui">' % (W, H)]
    for v in (0, 2, 4, 6, 8, 10):
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#2a3a3d"/><text x="%d" y="%.1f" font-size="10" fill="#8ea29d" text-anchor="end">%d</text>' % (L, W - 8, Y(v), Y(v), L - 6, Y(v) + 3, v))
    for s in range(0, int(length) + 1, 50):
        out.append('<text x="%.1f" y="%d" font-size="10" fill="#8ea29d" text-anchor="middle">%d m</text>' % (X(s), H - 6, s))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#ff5b4f" stroke-dasharray="4 4"/>' % (L, W - 8, Y(4), Y(4)))
    for f in d["faults"]:
        out.append('<line x1="%.1f" x2="%.1f" y1="8" y2="%d" stroke="#f09a3a" stroke-dasharray="2 3"/><text x="%.1f" y="18" font-size="10" fill="#f09a3a">%s</text>' % (X(f["fence_s_m"]), X(f["fence_s_m"]), H - B, X(f["fence_s_m"]) + 3, f["id"]))
    if prof:
        pts = sorted(prof)
        out.append('<polyline points="%s" fill="none" stroke="#7fd3ff" stroke-width="1.6"/>' % " ".join("%.1f,%.1f" % (X(s), Y(v0)) for s, v0, _ in pts))
        out.append('<polyline points="%s" fill="none" stroke="#f2c230" stroke-width="1.8"/>' % " ".join("%.1f,%.1f" % (X(s), Y(v1)) for s, _, v1 in pts))
    out.append("</svg>")
    return "\n".join(out)


def write_html(d, path):
    m = d["mission"]
    rows_f = "".join(
        "<tr><td>{id}</td><td>{t}</td><td>{w}</td><td class=m>{lat:.6f}, {lon:.6f}</td><td>{s:.0f} m</td><td><span class='pill {pc}'>{p}</span></td></tr>".format(
            id=f["id"], t=html.escape(f["label"]), w=html.escape(f["where"]), lat=f["lat"], lon=f["lon"], s=f["fence_s_m"],
            p=PRIO.get(f["type"], ("", ""))[0], pc=PRIO.get(f["type"], ("", ""))[1]) for f in d["faults"]) or "<tr><td colspan=6>Niciun defect găsit.</td></tr>"
    rows_a = "".join(
        "<tr><td>{id}</td><td>{sp}</td><td class=m>{lat:.6f}, {lon:.6f}</td><td>{df:.0f} m</td><td>{nf}</td></tr>".format(
            id=a["id"], sp=a["species"], lat=a["lat"], lon=a["lon"], df=a["distance_to_fence_m"], nf=a["near_fault"]) for a in d["escaped_animals"]) or "<tr><td colspan=5>Niciun animal în afara gardului.</td></tr>"
    h = d["herd"]
    doc = """<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raport gard · {gen}</title>
<style>
:root{{--bg:#0b1517;--card:#0f1d21;--fg:#e6efe9;--mut:#8ea29d;--line:rgba(190,225,214,.14);--volt:#f2c230;--crit:#ff5b4f;--warn:#f09a3a}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"Helvetica Neue",system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:28px max(16px,env(safe-area-inset-left,0px)) 48px;display:grid;gap:22px}}
h1{{margin:0;font-size:26px}} h2{{margin:0 0 8px;font-size:16px}} .sub{{color:var(--mut);font-size:13px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.k div{{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--card)}}
.k b{{display:block;font:600 20px/1.2 ui-monospace,Menlo,monospace}} .k span{{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}}
svg{{width:100%;height:auto;display:block;border-radius:8px;background:var(--card);font-family:-apple-system,system-ui,sans-serif}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th{{text-align:left;font-weight:500;color:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--line);padding:6px 8px}}
td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}} td.m{{font:12.5px ui-monospace,Menlo,monospace;white-space:nowrap}}
.t{{overflow-x:auto}} .pill{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px}} .crit{{background:rgba(255,91,79,.15);color:var(--crit)}} .warn{{background:rgba(240,154,58,.15);color:var(--warn)}}
.lg{{display:flex;gap:14px;font-size:12px;color:var(--mut);flex-wrap:wrap}} .lg i{{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:5px}}
.note{{color:var(--mut);font-size:13.5px;max-width:68ch}}
</style></head><body><main>
<div><h1>Raport inspecție gard electric</h1><div class="sub">{gen} · {drone} · origine {lat:.5f}, {lon:.5f}</div></div>
<div class="k">
 <div><span>Defecte</span><b style="color:var(--warn)">{nf}</b></div>
 <div><span>Animale evadate</span><b style="color:var(--crit)">{ne}</b></div>
 <div><span>Animale văzute</span><b>{seen}/{total}</b></div>
 <div><span>Durată zbor</span><b>{dm}:{ds:02d}</b></div>
 <div><span>Distanță</span><b>{dist} m</b></div>
 <div><span>Gard inspectat</span><b>{fl} m</b></div>
</div>
<section><h2>Harta</h2>{map}<div class="lg" style="margin-top:8px"><span><i style="background:var(--volt)"></i>gard</span><span><i style="background:#7fd3ff"></i>traseul dronei</span><span><i style="background:var(--warn)"></i>defect</span><span><i style="background:var(--crit)"></i>animal evadat</span></div></section>
<section><h2>Defecte găsite</h2><div class="t"><table><thead><tr><th>#</th><th>Ce</th><th>Unde</th><th>GPS</th><th>De la energizator</th><th>Prioritate</th></tr></thead><tbody>{rf}</tbody></table></div></section>
<section><h2>Animale în afara gardului</h2><div class="t"><table><thead><tr><th>ID</th><th>Specie</th><th>Ultima poziție</th><th>Distanță de gard</th><th>Lângă defectul</th></tr></thead><tbody>{ra}</tbody></table></div></section>
<section><h2>Tensiunea gardului (senzor EM, kV)</h2>{em}<div class="lg" style="margin-top:8px"><span><i style="background:var(--volt)"></i>fir sus</span><span><i style="background:#7fd3ff"></i>fir jos</span><span><i style="background:var(--crit)"></i>prag 4 kV</span></div></section>
<p class="note">{ns} animale nu au intrat în câmpul camerei: un tur pe lângă gard vede cam 15–20 m spre interior. Pentru numărarea completă a turmei adaugă un zbor în grilă peste mijlocul pășunii. Detecțiile din simulare folosesc pozițiile reale din Gazebo; pe drona reală vin dintr-un model de detecție pe imaginea camerei.</p>
</main></body></html>""".format(
        gen=html.escape(d["generated_at"].replace("T", " ")), drone=html.escape(d["drone"]), lat=d["origin"]["lat"], lon=d["origin"]["lon"],
        nf=len(d["faults"]), ne=len(d["escaped_animals"]), seen=h["seen"], total=h["total"], dm=m["duration_s"] // 60, ds=m["duration_s"] % 60,
        dist=m["distance_m"], fl=m["fence_length_m"], map=_map_svg(d), rf=rows_f, ra=rows_a, em=_em_svg(d, m["fence_length_m"]), ns=h["not_seen"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], encoding="utf-8") as f:
        print(write_html(json.load(f), sys.argv[1].replace(".json", ".html")))
