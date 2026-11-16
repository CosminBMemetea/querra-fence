"""English / Romanian strings for everything the simulation shows to a person.

Pick the language with `GARDIAN_LANG=ro` (or `./start.sh --lang ro`); English is the default.
Logs and JSON data always stay in English so other tools can read them.
"""
import os

LANG = (os.environ.get("GARDIAN_LANG") or "en").strip().lower()[:2]
if LANG not in ("en", "ro"):
    LANG = "en"

MSG = {
    # mission.py
    "title": ("Gardian X500 · fence inspection mission ({m:.0f} m of fence, {n} route points)",
              "Gardian X500 · misiune de inspecție a gardului ({m:.0f} m de gard, {n} puncte de traseu)"),
    "waiting_px4": ("Waiting for PX4 on {url} …", "Aștept PX4 pe {url} …"),
    "px4_silent": ("PX4 is not answering. Check run/px4.log.", "PX4 nu răspunde. Verifică run/px4.log."),
    "px4_ok": ("PX4 connected.", "PX4 conectat."),
    "params_ok": ("Smooth-flight parameters set.", "Parametrii de zbor lin sunt setați."),
    "params_missing": ("Smooth-flight parameters set (missing: {names}).", "Parametrii de zbor lin sunt setați (lipsesc: {names})."),
    "wait_gps": ("Waiting for GPS and the estimator …", "Aștept GPS-ul și estimatorul …"),
    "gps": ("GPS fix {fix} · {sats} satellites · home at {lat:.6f}, {lon:.6f}", "GPS fix {fix} · {sats} sateliți · acasă la {lat:.6f}, {lon:.6f}"),
    "upload_fail": ("Could not upload the mission.", "Nu am putut urca misiunea."),
    "uploaded": ("Mission uploaded: {items} items (takeoff, {n} points along the fence, return).",
                 "Misiune urcată: {items} comenzi (decolare, {n} puncte pe lângă gard, întoarcere)."),
    "wait_go": ("Waiting for the start signal ({name}) …", "Aștept semnalul de start ({name}) …"),
    "wait_arm": ("Waiting for PX4 to allow arming …", "Aștept ca PX4 să permită armarea …"),
    "not_yet": ("  not yet: {reason}", "  încă nu: {reason}"),
    "no_arm": ("PX4 did not arm. Last messages: {texts}", "PX4 nu a armat. Ultimele mesaje: {texts}"),
    "armed": ("Armed. Taking off to {alt:.0f} m …", "Armat. Decolare la {alt:.0f} m …"),
    "fault_line": ("  FAULT    {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                   "  DEFECT   {id} — {label} · {where} · {lat:.6f}, {lon:.6f}"),
    "escaped_line": ("  ESCAPED  {id} ({species}) · {dist:.0f} m outside the fence, near {near} · {lat:.6f}, {lon:.6f}",
                     "  EVADAT   {id} ({species}) · {dist:.0f} m în afara gardului, lângă {near} · {lat:.6f}, {lon:.6f}"),
    "em_line": ("  EM       Top wire is dead from ~{s:.0f} m after the energizer (the wire is broken before this point)",
                "  EM       Firul de sus nu mai are tensiune de la ~{s:.0f} m de energizator (fir întrerupt înainte de punctul ăsta)"),
    "timeout": ("Time limit reached (15 min), stopping the monitor.", "Timp depășit (15 min), opresc monitorizarea."),
    "stopped": ("Stopped by hand. Saving a partial report.", "Oprit manual. Salvez raportul parțial."),
    "landed": ("Landed. Flight time {mm}:{ss:02d} · {dist:.0f} m flown.", "Aterizat. Durată {mm}:{ss:02d} · {dist:.0f} m zburați."),
    "report": ("Report: {path}", "Raport: {path}"),
    "summary": ("  {f} faults · {e} escaped animals · {seen}/{total} animals seen",
                "  {f} defecte · {e} animale evadate · {seen}/{total} animale văzute"),
    "status": ("  fence {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · faults {f} · escaped {e} · seen {seen}/{total}",
               "  gard {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · defecte {f} · evadate {e} · văzute {seen}/{total}"),
    "ph_preflight": ("Preflight", "Pregătire"),
    "ph_takeoff": ("Takeoff", "Decolare"),
    "ph_transit": ("Takeoff / transit", "Decolare / tranzit"),
    "ph_inspection": ("Fence inspection", "Inspecție gard"),
    "ph_return": ("Return", "Întoarcere"),
    "ph_landing": ("Landing", "Aterizare"),
    "em_event": ("0 kV on the top wire", "0 kV pe firul de sus"),
    # ground/node.py (the ground station)
    "g_start": ("Ground station on · cameras: {cams} · fence alarm below {kv:.1f} kV",
                "Stația de sol pornită · camere: {cams} · alarmă gard sub {kv:.1f} kV"),
    "g_status": ("Ground station · {n} animals in view · fence {e:.1f} kV at the energizer, {end} at the far end",
                 "Stația de sol · {n} animale în cadru · gard {e:.1f} kV la energizator, {end} la capăt"),
    "g_outside": ("  GROUND   {id} ({species}) is outside the fence, {dist:.0f} m from the gate · seen by {cam}",
                  "  SOL      {id} ({species}) e în afara gardului, la {dist:.0f} m de poartă · văzut de {cam}"),
    "g_gate": ("  GROUND   {id} went {dir} through the gate (iToF) · {n} animals out through the gate so far",
               "  SOL      {id} a ieșit {dir} pe poartă (iToF) · {n} animale ieșite pe poartă până acum"),
    "g_volt": ("  GROUND   Fence monitor: {wire} wire at the far end is at {kv:.1f} kV (alarm below {thr:.1f} kV)",
               "  SOL      Monitor gard: firul {wire} de la capătul gardului are {kv:.1f} kV (alarmă sub {thr:.1f} kV)"),
    "g_dispatch": ("  GROUND → AIR  Sending the drone to check: {reason}",
                   "  SOL → AER    Trimit drona să verifice: {reason}"),
    "g_busy": ("  GROUND   The drone is already out; the alert goes into its report.",
               "  SOL      Drona e deja în aer; alerta intră în raportul ei."),
    "guard_wait": ("Guard mode: the ground station watches; the drone takes off when it raises an alert. Ctrl+C stops everything.",
                   "Mod de pază: stația de sol veghează; drona decolează când apare o alertă. Ctrl+C oprește tot."),
    "trigger": ("Triggered by the ground station: {reason}", "Declanșat de stația de sol: {reason}"),
}

REASON = {
    "animal_outside": ("animal outside the fence near the gate", "animal în afara gardului lângă poartă"),
    "gate_exit": ("animal left through the gate", "animal ieșit pe poartă"),
    "voltage": ("fence voltage alarm", "alarmă de tensiune pe gard"),
}
WIRE = {0: ("bottom", "de jos"), 1: ("top", "de sus")}
DIRECTION = {"out": ("out", "afară"), "in": ("in", "înăuntru")}
CAM = {"rgb": ("RGB camera", "camera RGB"), "thermal": ("thermal camera", "camera termală"), "depth": ("iToF", "iToF")}

FAULT = {
    "wire_break": ("Broken wire (top strand)", "Sârmă ruptă (firul de sus)"),
    "post_down": ("Fallen post, wires on the ground", "Stâlp căzut, sârmele ating solul"),
    "branch_short": ("Branch on the fence, short circuit", "Creangă pe gard, scurtcircuit"),
}
FAULT_SHORT = {
    "wire_break": ("Broken wire", "Sârmă ruptă"),
    "post_down": ("Fallen post", "Stâlp căzut"),
    "branch_short": ("Branch on fence", "Creangă pe gard"),
}
WHERE = {
    "post": ("post {post}", "stâlpul {post}"),
    "segment": ("posts {a}–{b}", "între stâlpii {a}–{b}"),
}
SPECIES = {"cow": ("cow", "vacă"), "sheep": ("sheep", "oaie")}


def pick(pair, lang=None):
    return pair[1] if (lang or LANG) == "ro" else pair[0]


def t(key, lang=None, **kw):
    return pick(MSG[key], lang).format(**kw)


def both(pair, **kw):
    """{"en": ..., "ro": ...} for JSON fields a person reads."""
    return {"en": pair[0].format(**kw), "ro": pair[1].format(**kw)}
