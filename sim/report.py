"""HTML inspection report (SVG map + EM voltage profile), English | Romanian with a switch.

The page opens in the language the mission ran in (GARDIAN_LANG); `#en` or `#ro` in the
URL, or the EN | RO buttons, switch it.
"""
import html
import json

import i18n

PRIO = {"wire_break": (("Urgent", "Urgent"), "crit"), "post_down": (("Urgent", "Urgent"), "crit"),
        "branch_short": (("Today", "Azi"), "warn")}


def L(en, ro=None):
    """Both languages in the page; CSS shows one."""
    if ro is None:
        en, ro = en
    return '<span class="l-en">%s</span><span class="l-ro">%s</span>' % (html.escape(en), html.escape(ro))


def text2(field):
    """A JSON text field: {"en":..,"ro":..} or a plain string (older reports)."""
    if isinstance(field, dict):
        return field.get("en", ""), field.get("ro", field.get("en", ""))
    return field, field


def species2(code):
    old = {"vacă": "cow", "oaie": "sheep"}
    return i18n.SPECIES.get(old.get(code, code), (code, code))


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

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Pasture map with faults and escaped animals">' % (W, H)]
    out.append('<rect width="100%" height="100%" fill="#16241b"/>')
    out.append('<polygon points="%s" fill="#24402a" stroke="none"/>' % " ".join(P(*p) for p in d["fence_polygon"]))
    out.append('<polyline points="%s" fill="none" stroke="#f2c230" stroke-width="2"/>' % " ".join(P(*p) for p in d["posts"]))
    if d["track"]:
        out.append('<polyline points="%s" fill="none" stroke="#7fd3ff" stroke-width="1.6" stroke-dasharray="5 4" opacity=".85"/>' % " ".join(P(*p) for p in d["track"]))
    out.append('<g transform="translate(%s)"><circle r="7" fill="#0e1c20" stroke="#e6efe9"/><text y="4" text-anchor="middle" font-size="10" fill="#e6efe9" font-weight="700">H</text></g>' % P(0, 0))
    for f in d["faults"]:
        en, ro = i18n.FAULT_SHORT.get(f["type"], ("", ""))
        out.append('<g transform="translate(%s)"><circle r="10" fill="none" stroke="#f09a3a" stroke-width="2.5"/><circle r="3" fill="#f09a3a"/>'
                   '<text class="l-en" x="14" y="4" font-size="12" fill="#f09a3a" font-weight="600">%s %s</text>'
                   '<text class="l-ro" x="14" y="4" font-size="12" fill="#f09a3a" font-weight="600">%s %s</text></g>'
                   % (P(f["x"], f["y"]), f["id"], html.escape(en), f["id"], html.escape(ro)))
    for a in d["escaped_animals"]:
        out.append('<g transform="translate(%s)"><circle r="6" fill="#ff5b4f"/><text x="10" y="4" font-size="11" fill="#ff8a80">%s</text></g>' % (P(a["x"], a["y"]), a["id"]))
    out.append("</svg>")
    return "\n".join(out)


def _em_svg(d, length):
    prof = d["em_profile"]
    W, H, Lm, B = 760, 170, 34, 22
    vmax = 10.0

    def X(s):
        return Lm + (W - Lm - 8) * s / max(1.0, length)

    def Y(v):
        return 8 + (H - B - 8) * (1 - v / vmax)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Fence voltage measured along the fence">' % (W, H)]
    for v in (0, 2, 4, 6, 8, 10):
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#2a3a3d"/><text x="%d" y="%.1f" font-size="10" fill="#8ea29d" text-anchor="end">%d</text>' % (Lm, W - 8, Y(v), Y(v), Lm - 6, Y(v) + 3, v))
    for s in range(0, int(length) + 1, 50):
        out.append('<text x="%.1f" y="%d" font-size="10" fill="#8ea29d" text-anchor="middle">%d m</text>' % (X(s), H - 6, s))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#ff5b4f" stroke-dasharray="4 4"/>' % (Lm, W - 8, Y(4), Y(4)))
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
            id=f["id"], t=L(text2(f["label"])), w=L(text2(f["where"])), lat=f["lat"], lon=f["lon"], s=f["fence_s_m"],
            p=L(PRIO.get(f["type"], (("", ""), ""))[0]), pc=PRIO.get(f["type"], (("", ""), ""))[1]) for f in d["faults"]
    ) or "<tr><td colspan=6>%s</td></tr>" % L("No faults found.", "Niciun defect găsit.")
    rows_a = "".join(
        "<tr><td>{id}</td><td>{sp}</td><td class=m>{lat:.6f}, {lon:.6f}</td><td>{df:.0f} m</td><td>{nf}</td></tr>".format(
            id=a["id"], sp=L(species2(a["species"])), lat=a["lat"], lon=a["lon"], df=a["distance_to_fence_m"], nf=L("gate", "poartă") if a["near_fault"] == "gate" else a["near_fault"])
        for a in d["escaped_animals"]
    ) or "<tr><td colspan=5>%s</td></tr>" % L("No animals outside the fence.", "Niciun animal în afara gardului.")
    h = d["herd"]
    lang = d.get("language", "en")
    doc = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fence report · {gen}</title>
<style>
:root{{--bg:#0b1517;--card:#0f1d21;--fg:#e6efe9;--mut:#8ea29d;--line:rgba(190,225,214,.14);--volt:#f2c230;--crit:#ff5b4f;--warn:#f09a3a}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"Helvetica Neue",system-ui,sans-serif}}
body.ro .l-en, body:not(.ro) .l-ro{{display:none}}
main{{max-width:820px;margin:0 auto;padding:28px max(16px,env(safe-area-inset-left,0px)) 48px;display:grid;gap:22px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}}
h1{{margin:0;font-size:26px}} h2{{margin:0 0 8px;font-size:16px}} .sub{{color:var(--mut);font-size:13px}}
.lang{{display:inline-flex;border:1px solid var(--line);border-radius:8px;padding:2px;gap:2px}}
.lang button{{font:600 12px/1 inherit;color:var(--mut);background:none;border:0;border-radius:6px;padding:7px 10px;cursor:pointer;letter-spacing:.06em}}
.lang button[aria-pressed=true]{{background:rgba(242,194,48,.16);color:var(--volt)}}
.lang button:focus-visible{{outline:2px solid var(--volt);outline-offset:2px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.k div{{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--card)}}
.k b{{display:block;font:600 20px/1.2 ui-monospace,Menlo,monospace}} .k span{{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}}
svg{{width:100%;height:auto;display:block;border-radius:8px;background:var(--card);font-family:-apple-system,system-ui,sans-serif}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th{{text-align:left;font-weight:500;color:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--line);padding:6px 8px}}
td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}} td.m{{font:12.5px ui-monospace,Menlo,monospace;white-space:nowrap}}
.t{{overflow-x:auto}} .pill{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px}} .crit{{background:rgba(255,91,79,.15);color:var(--crit)}} .warn{{background:rgba(240,154,58,.15);color:var(--warn)}}
.lg{{display:flex;gap:14px;font-size:12px;color:var(--mut);flex-wrap:wrap}} .lg i{{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:5px}}
.note{{color:var(--mut);font-size:13.5px;max-width:68ch}}
</style></head><body class="{bodyclass}"><main>
<header>
 <div><h1>{t_title}</h1><div class="sub">{gen} · {drone} · {t_origin} {lat:.5f}, {lon:.5f}</div>{trig}</div>
 <div class="lang" role="group" aria-label="Language"><button type="button" data-l="en">EN</button><button type="button" data-l="ro">RO</button></div>
</header>
<div class="k">
 <div><span>{t_faults}</span><b style="color:var(--warn)">{nf}</b></div>
 <div><span>{t_escaped}</span><b style="color:var(--crit)">{ne}</b></div>
 <div><span>{t_seen}</span><b>{seen}/{total}</b></div>
 <div><span>{t_time}</span><b>{dm}:{ds:02d}</b></div>
 <div><span>{t_dist}</span><b>{dist} m</b></div>
 <div><span>{t_fence}</span><b>{fl} m</b></div>
</div>
<section><h2>{t_map}</h2>{map}<div class="lg" style="margin-top:8px"><span><i style="background:var(--volt)"></i>{t_lg_fence}</span><span><i style="background:#7fd3ff"></i>{t_lg_track}</span><span><i style="background:var(--warn)"></i>{t_lg_fault}</span><span><i style="background:var(--crit)"></i>{t_lg_animal}</span></div></section>
<section><h2>{t_faults_found}</h2><div class="t"><table><thead><tr><th>#</th><th>{t_what}</th><th>{t_where}</th><th>GPS</th><th>{t_from}</th><th>{t_prio}</th></tr></thead><tbody>{rf}</tbody></table></div></section>
<section><h2>{t_outside}</h2><div class="t"><table><thead><tr><th>ID</th><th>{t_species}</th><th>{t_last}</th><th>{t_dfence}</th><th>{t_near}</th></tr></thead><tbody>{ra}</tbody></table></div></section>
<section><h2>{t_volt}</h2>{em}<div class="lg" style="margin-top:8px"><span><i style="background:var(--volt)"></i>{t_top}</span><span><i style="background:#7fd3ff"></i>{t_bottom}</span><span><i style="background:var(--crit)"></i>{t_thr}</span></div></section>
<p class="note">{t_note}</p>
</main>
<script>
(function () {{
  var body = document.body, btns = document.querySelectorAll('.lang button');
  function set(l) {{
    body.classList.toggle('ro', l === 'ro');
    document.documentElement.lang = l;
    btns.forEach(function (b) {{ b.setAttribute('aria-pressed', String(b.dataset.l === l)); }});
  }}
  var start = (location.hash === '#ro' || location.hash === '#en') ? location.hash.slice(1) : null;
  if (!start) {{ try {{ start = localStorage.getItem('gardian-lang'); }} catch (e) {{}} }}
  set(start || '{lang}');
  btns.forEach(function (b) {{ b.addEventListener('click', function () {{
    set(b.dataset.l); try {{ localStorage.setItem('gardian-lang', b.dataset.l); }} catch (e) {{}}
  }}); }});
}})();
</script>
</body></html>""".format(
        lang=lang, bodyclass="ro" if lang == "ro" else "",
        trig=('<div class="sub" style="color:#7fd3ff;margin-top:4px">%s</div>' % L(
            i18n.MSG["trigger"][0].format(reason=text2(d["trigger"]["label"])[0]),
            i18n.MSG["trigger"][1].format(reason=text2(d["trigger"]["label"])[1]))) if d.get("trigger") else "",
        gen=html.escape(d["generated_at"].replace("T", " ")), drone=html.escape(d["drone"]), lat=d["origin"]["lat"], lon=d["origin"]["lon"],
        nf=len(d["faults"]), ne=len(d["escaped_animals"]), seen=h["seen"], total=h["total"], dm=m["duration_s"] // 60, ds=m["duration_s"] % 60,
        dist=m["distance_m"], fl=m["fence_length_m"], map=_map_svg(d), rf=rows_f, ra=rows_a, em=_em_svg(d, m["fence_length_m"]),
        t_title=L("Electric fence inspection report", "Raport inspecție gard electric"), t_origin=L("origin", "origine"),
        t_faults=L("Faults", "Defecte"), t_escaped=L("Escaped animals", "Animale evadate"), t_seen=L("Animals seen", "Animale văzute"),
        t_time=L("Flight time", "Durată zbor"), t_dist=L("Distance", "Distanță"), t_fence=L("Fence inspected", "Gard inspectat"),
        t_map=L("Map", "Harta"), t_lg_fence=L("fence", "gard"), t_lg_track=L("drone track", "traseul dronei"),
        t_lg_fault=L("fault", "defect"), t_lg_animal=L("escaped animal", "animal evadat"),
        t_faults_found=L("Faults found", "Defecte găsite"), t_what=L("What", "Ce"), t_where=L("Where", "Unde"),
        t_from=L("From energizer", "De la energizator"), t_prio=L("Priority", "Prioritate"),
        t_outside=L("Animals outside the fence", "Animale în afara gardului"), t_species=L("Species", "Specie"),
        t_last=L("Last position", "Ultima poziție"), t_dfence=L("Distance to fence", "Distanță de gard"), t_near=L("Near fault", "Lângă defectul"),
        t_volt=L("Fence voltage (EM sensor, kV)", "Tensiunea gardului (senzor EM, kV)"),
        t_top=L("top wire", "fir sus"), t_bottom=L("bottom wire", "fir jos"), t_thr=L("4 kV threshold", "prag 4 kV"),
        t_note=L("%d animals never entered the camera view: a pass along the fence sees about 15–20 m into the paddock. "
                 "Counting the whole herd needs an extra grid flight over the middle of the pasture. Detections in the simulation "
                 "use the true positions from Gazebo; on the real drone they come from a vision model on the camera images." % h["not_seen"],
                 "%d animale nu au intrat în câmpul camerei: un tur pe lângă gard vede cam 15–20 m spre interior. "
                 "Pentru numărarea completă a turmei adaugă un zbor în grilă peste mijlocul pășunii. Detecțiile din simulare folosesc "
                 "pozițiile reale din Gazebo; pe drona reală vin dintr-un model de detecție pe imaginea camerei." % h["not_seen"]),
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], encoding="utf-8") as f:
        print(write_html(json.load(f), sys.argv[1].replace(".json", ".html")))
