"""Strings for everything the simulation shows to a person, in nine languages.

EN English · RO Română · PL Polski · PT Português · DE Deutsch · ES Español · HR Hrvatski · BG Български · DA Dansk
Pick the language with `GARDIAN_LANG=pl` (or `./start.sh --lang pl`); English is the default.
Logs and JSON data always stay in English so other tools can read them; text fields a person reads are stored in
JSON in every language (see both()), so the report can switch language after the flight.

Every entry is _(en, ro, pl, pt, de, es, hr, bg, da), in that order.
"""
import os

LANGS = ("en", "ro", "pl", "pt", "de", "es", "hr", "bg", "da")
LANG_NAMES = {"en": "English", "ro": "Română", "pl": "Polski", "pt": "Português", "de": "Deutsch", "es": "Español",
              "hr": "Hrvatski", "bg": "Български", "da": "Dansk"}


def _(*s):
    assert len(s) == len(LANGS), s[0]
    return dict(zip(LANGS, s))


LANG = (os.environ.get("GARDIAN_LANG") or "en").strip().lower()[:2]
if LANG not in LANGS:
    LANG = "en"

MSG = {
    # mission.py
    "title": _("Gardian X500 · fence inspection mission ({m:.0f} m of fence, {n} route points)",
               "Gardian X500 · misiune de inspecție a gardului ({m:.0f} m de gard, {n} puncte de traseu)",
               "Gardian X500 · misja inspekcji ogrodzenia ({m:.0f} m ogrodzenia, {n} punktów trasy)",
               "Gardian X500 · missão de inspeção da cerca ({m:.0f} m de cerca, {n} pontos de rota)",
               "Gardian X500 · Zaunkontrollflug ({m:.0f} m Zaun, {n} Routenpunkte)",
               "Gardian X500 · misión de inspección de la cerca ({m:.0f} m de cerca, {n} puntos de ruta)",
               "Gardian X500 · misija pregleda ograde ({m:.0f} m ograde, {n} točaka rute)",
               "Gardian X500 · мисия за проверка на оградата ({m:.0f} м ограда, {n} точки по маршрута)",
               "Gardian X500 · inspektion af hegnet ({m:.0f} m hegn, {n} rutepunkter)"),
    "waiting_px4": _("Waiting for PX4 on {url} …", "Aștept PX4 pe {url} …", "Czekam na PX4 pod {url} …",
                     "A aguardar o PX4 em {url} …", "Warte auf PX4 unter {url} …", "Esperando a PX4 en {url} …",
                     "Čekam PX4 na {url} …", "Изчаквам PX4 на {url} …", "Venter på PX4 på {url} …"),
    "px4_silent": _("PX4 is not answering. Check run/px4.log.", "PX4 nu răspunde. Verifică run/px4.log.",
                    "PX4 nie odpowiada. Sprawdź run/px4.log.", "O PX4 não responde. Verifique run/px4.log.",
                    "PX4 antwortet nicht. Siehe run/px4.log.", "PX4 no responde. Revisa run/px4.log.",
                    "PX4 ne odgovara. Provjeri run/px4.log.", "PX4 не отговаря. Провери run/px4.log.",
                    "PX4 svarer ikke. Se run/px4.log."),
    "px4_ok": _("PX4 connected.", "PX4 conectat.", "PX4 połączony.", "PX4 ligado.", "PX4 verbunden.", "PX4 conectado.",
                "PX4 povezan.", "PX4 е свързан.", "PX4 forbundet."),
    "params_ok": _("Smooth-flight parameters set.", "Parametrii de zbor lin sunt setați.", "Ustawiono parametry płynnego lotu.",
                   "Parâmetros de voo suave definidos.", "Parameter für ruhigen Flug gesetzt.",
                   "Parámetros de vuelo suave configurados.", "Postavljeni parametri za mirni let.",
                   "Параметрите за плавен полет са зададени.", "Parametre for blød flyvning er sat."),
    "params_missing": _("Smooth-flight parameters set (missing: {names}).", "Parametrii de zbor lin sunt setați (lipsesc: {names}).",
                        "Ustawiono parametry płynnego lotu (brakuje: {names}).",
                        "Parâmetros de voo suave definidos (em falta: {names}).",
                        "Parameter für ruhigen Flug gesetzt (fehlen: {names}).",
                        "Parámetros de vuelo suave configurados (faltan: {names}).",
                        "Postavljeni parametri za mirni let (nedostaju: {names}).",
                        "Параметрите за плавен полет са зададени (липсват: {names}).",
                        "Parametre for blød flyvning er sat (mangler: {names})."),
    "wait_gps": _("Waiting for GPS and the estimator …", "Aștept GPS-ul și estimatorul …", "Czekam na GPS i estymator …",
                  "A aguardar o GPS e o estimador …", "Warte auf GPS und Schätzer …", "Esperando al GPS y al estimador …",
                  "Čekam GPS i estimator …", "Изчаквам GPS и оценителя …", "Venter på GPS og estimatoren …"),
    "gps": _("GPS fix {fix} · {sats} satellites · home at {lat:.6f}, {lon:.6f}",
             "GPS fix {fix} · {sats} sateliți · acasă la {lat:.6f}, {lon:.6f}",
             "Fix GPS {fix} · {sats} satelitów · baza: {lat:.6f}, {lon:.6f}",
             "GPS fix {fix} · {sats} satélites · casa em {lat:.6f}, {lon:.6f}",
             "GPS-Fix {fix} · {sats} Satelliten · Startpunkt {lat:.6f}, {lon:.6f}",
             "Fix GPS {fix} · {sats} satélites · base en {lat:.6f}, {lon:.6f}",
             "GPS fix {fix} · {sats} satelita · polazište {lat:.6f}, {lon:.6f}",
             "GPS fix {fix} · {sats} сателита · начална точка {lat:.6f}, {lon:.6f}",
             "GPS-fix {fix} · {sats} satellitter · hjem ved {lat:.6f}, {lon:.6f}"),
    "upload_fail": _("Could not upload the mission.", "Nu am putut urca misiunea.", "Nie udało się wgrać misji.",
                     "Não foi possível carregar a missão.", "Mission konnte nicht hochgeladen werden.",
                     "No se pudo cargar la misión.", "Misiju nije moguće učitati.", "Мисията не можа да се зареди.",
                     "Kunne ikke uploade missionen."),
    "uploaded": _("Mission uploaded: {items} items (takeoff, {n} points along the fence, return).",
                  "Misiune urcată: {items} comenzi (decolare, {n} puncte pe lângă gard, întoarcere).",
                  "Misja wgrana: {items} poleceń (start, {n} punktów wzdłuż ogrodzenia, powrót).",
                  "Missão carregada: {items} itens (descolagem, {n} pontos ao longo da cerca, regresso).",
                  "Mission hochgeladen: {items} Einträge (Start, {n} Punkte entlang des Zauns, Rückkehr).",
                  "Misión cargada: {items} elementos (despegue, {n} puntos a lo largo de la cerca, regreso).",
                  "Misija učitana: {items} naredbi (polijetanje, {n} točaka uz ogradu, povratak).",
                  "Мисията е заредена: {items} команди (излитане, {n} точки покрай оградата, връщане).",
                  "Mission uploadet: {items} punkter (start, {n} punkter langs hegnet, retur)."),
    "wait_go": _("Waiting for the start signal ({name}) …", "Aștept semnalul de start ({name}) …",
                 "Czekam na sygnał startu ({name}) …", "A aguardar o sinal de partida ({name}) …",
                 "Warte auf das Startsignal ({name}) …", "Esperando la señal de inicio ({name}) …",
                 "Čekam signal za početak ({name}) …", "Изчаквам сигнала за старт ({name}) …",
                 "Venter på startsignalet ({name}) …"),
    "wait_arm": _("Waiting for PX4 to allow arming …", "Aștept ca PX4 să permită armarea …",
                  "Czekam, aż PX4 pozwoli uzbroić drona …", "A aguardar que o PX4 permita armar …",
                  "Warte, bis PX4 das Scharfschalten erlaubt …", "Esperando a que PX4 permita armar …",
                  "Čekam da PX4 dopusti aktiviranje …", "Изчаквам PX4 да позволи активиране …",
                  "Venter på, at PX4 tillader armering …"),
    "not_yet": _("  not yet: {reason}", "  încă nu: {reason}", "  jeszcze nie: {reason}", "  ainda não: {reason}",
                 "  noch nicht: {reason}", "  todavía no: {reason}", "  još ne: {reason}", "  все още не: {reason}",
                 "  ikke endnu: {reason}"),
    "no_arm": _("PX4 did not arm. Last messages: {texts}", "PX4 nu a armat. Ultimele mesaje: {texts}",
                "PX4 nie uzbroił drona. Ostatnie komunikaty: {texts}", "O PX4 não armou. Últimas mensagens: {texts}",
                "PX4 wurde nicht scharfgeschaltet. Letzte Meldungen: {texts}", "PX4 no se armó. Últimos mensajes: {texts}",
                "PX4 se nije aktivirao. Posljednje poruke: {texts}", "PX4 не се активира. Последни съобщения: {texts}",
                "PX4 blev ikke armeret. Seneste meddelelser: {texts}"),
    "armed": _("Armed. Taking off to {alt:.0f} m …", "Armat. Decolare la {alt:.0f} m …", "Uzbrojony. Start na {alt:.0f} m …",
               "Armado. A descolar para {alt:.0f} m …", "Scharf. Start auf {alt:.0f} m …",
               "Armado. Despegando a {alt:.0f} m …", "Aktiviran. Polijetanje na {alt:.0f} m …",
               "Активиран. Излитане до {alt:.0f} м …", "Armeret. Letter til {alt:.0f} m …"),
    "fault_line": _("  FAULT    {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  DEFECT   {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  USTERKA  {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  AVARIA   {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  SCHADEN  {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  AVERÍA   {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  KVAR     {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  ПОВРЕДА  {id} — {label} · {where} · {lat:.6f}, {lon:.6f}",
                    "  FEJL     {id} — {label} · {where} · {lat:.6f}, {lon:.6f}"),
    "escaped_line": _("  ESCAPED  {id} ({species}) · {dist:.0f} m outside the fence, near {near} · {lat:.6f}, {lon:.6f}",
                      "  EVADAT   {id} ({species}) · {dist:.0f} m în afara gardului, lângă {near} · {lat:.6f}, {lon:.6f}",
                      "  ZBIEGŁE  {id} ({species}) · {dist:.0f} m poza ogrodzeniem, przy {near} · {lat:.6f}, {lon:.6f}",
                      "  FUGIDO   {id} ({species}) · {dist:.0f} m fora da cerca, perto de {near} · {lat:.6f}, {lon:.6f}",
                      "  ENTLAUFEN {id} ({species}) · {dist:.0f} m außerhalb des Zauns, nahe {near} · {lat:.6f}, {lon:.6f}",
                      "  ESCAPADO {id} ({species}) · {dist:.0f} m fuera de la cerca, junto a {near} · {lat:.6f}, {lon:.6f}",
                      "  ODBJEGLO {id} ({species}) · {dist:.0f} m izvan ograde, blizu {near} · {lat:.6f}, {lon:.6f}",
                      "  ИЗБЯГАЛО {id} ({species}) · на {dist:.0f} м извън оградата, близо до {near} · {lat:.6f}, {lon:.6f}",
                      "  UNDSLUPPET {id} ({species}) · {dist:.0f} m uden for hegnet, nær {near} · {lat:.6f}, {lon:.6f}"),
    "em_line": _("  EM       Top wire is dead from ~{s:.0f} m after the energizer (the wire is broken before this point)",
                 "  EM       Firul de sus nu mai are tensiune de la ~{s:.0f} m de energizator (fir întrerupt înainte de punctul ăsta)",
                 "  EM       Górny drut jest bez napięcia od ~{s:.0f} m za elektryzatorem (drut jest zerwany przed tym punktem)",
                 "  EM       O fio de cima está sem tensão a partir de ~{s:.0f} m do eletrificador (o fio está partido antes deste ponto)",
                 "  EM       Der obere Draht ist ab ~{s:.0f} m hinter dem Weidezaungerät spannungslos (davor ist er gerissen)",
                 "  EM       El hilo superior no tiene tensión desde ~{s:.0f} m después del electrificador (está cortado antes de este punto)",
                 "  EM       Gornja žica je bez napona od ~{s:.0f} m iza električnog pastira (žica je prekinuta prije te točke)",
                 "  EM       Горната жица е без напрежение след ~{s:.0f} м от електропастира (скъсана е преди тази точка)",
                 "  EM       Den øverste tråd er uden strøm fra ~{s:.0f} m efter hegnsapparatet (tråden er brudt før dette punkt)"),
    "timeout": _("Time limit reached (15 min), stopping the monitor.", "Timp depășit (15 min), opresc monitorizarea.",
                 "Przekroczono limit czasu (15 min), zatrzymuję monitorowanie.",
                 "Limite de tempo atingido (15 min), a parar a monitorização.",
                 "Zeitlimit erreicht (15 min), Überwachung wird beendet.",
                 "Se alcanzó el límite de tiempo (15 min), detengo el monitoreo.",
                 "Dosegnuto vremensko ograničenje (15 min), zaustavljam nadzor.",
                 "Достигнат е лимитът от 15 мин, спирам наблюдението.",
                 "Tidsgrænsen er nået (15 min), stopper overvågningen."),
    "stopped": _("Stopped by hand. Saving a partial report.", "Oprit manual. Salvez raportul parțial.",
                 "Zatrzymano ręcznie. Zapisuję częściowy raport.", "Parado manualmente. A guardar um relatório parcial.",
                 "Manuell gestoppt. Teilbericht wird gespeichert.", "Detenido manualmente. Guardo un informe parcial.",
                 "Ručno zaustavljeno. Spremam djelomično izvješće.", "Спряно ръчно. Записвам частичен доклад.",
                 "Stoppet manuelt. Gemmer en delvis rapport."),
    "landed": _("Landed. Flight time {mm}:{ss:02d} · {dist:.0f} m flown.", "Aterizat. Durată {mm}:{ss:02d} · {dist:.0f} m zburați.",
                "Wylądował. Czas lotu {mm}:{ss:02d} · przeleciano {dist:.0f} m.",
                "Aterrou. Tempo de voo {mm}:{ss:02d} · {dist:.0f} m percorridos.",
                "Gelandet. Flugzeit {mm}:{ss:02d} · {dist:.0f} m geflogen.",
                "Aterrizado. Tiempo de vuelo {mm}:{ss:02d} · {dist:.0f} m recorridos.",
                "Sletio. Trajanje leta {mm}:{ss:02d} · preletjeno {dist:.0f} m.",
                "Кацна. Време на полета {mm}:{ss:02d} · изминати {dist:.0f} м.",
                "Landet. Flyvetid {mm}:{ss:02d} · {dist:.0f} m fløjet."),
    "report": _("Report: {path}", "Raport: {path}", "Raport: {path}", "Relatório: {path}", "Bericht: {path}",
                "Informe: {path}", "Izvješće: {path}", "Доклад: {path}", "Rapport: {path}"),
    "summary": _("  {f} faults · {e} escaped animals · {seen}/{total} animals seen",
                 "  {f} defecte · {e} animale evadate · {seen}/{total} animale văzute",
                 "  {f} usterek · {e} zbiegłych zwierząt · widziano {seen}/{total} zwierząt",
                 "  {f} avarias · {e} animais fugidos · {seen}/{total} animais vistos",
                 "  {f} Schäden · {e} entlaufene Tiere · {seen}/{total} Tiere gesehen",
                 "  {f} averías · {e} animales escapados · {seen}/{total} animales vistos",
                 "  {f} kvarova · {e} odbjeglih životinja · viđeno {seen}/{total} životinja",
                 "  {f} повреди · {e} избягали животни · видени {seen}/{total} животни",
                 "  {f} fejl · {e} undslupne dyr · {seen}/{total} dyr set"),
    "status": _("  fence {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · faults {f} · escaped {e} · seen {seen}/{total}",
                "  gard {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · defecte {f} · evadate {e} · văzute {seen}/{total}",
                "  ogrodzenie {pct:3d}% · wys {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · usterki {f} · zbiegłe {e} · widziane {seen}/{total}",
                "  cerca {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · avarias {f} · fugidos {e} · vistos {seen}/{total}",
                "  Zaun {pct:3d}% · Höhe {alt:4.1f} m · {spd:3.1f} m/s · Akku {bat} · Schäden {f} · entlaufen {e} · gesehen {seen}/{total}",
                "  cerca {pct:3d}% · alt {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · averías {f} · escapados {e} · vistos {seen}/{total}",
                "  ograda {pct:3d}% · vis {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · kvarovi {f} · odbjegli {e} · viđeno {seen}/{total}",
                "  ограда {pct:3d}% · вис {alt:4.1f} м · {spd:3.1f} м/с · бат {bat} · повреди {f} · избягали {e} · видени {seen}/{total}",
                "  hegn {pct:3d}% · højde {alt:4.1f} m · {spd:3.1f} m/s · bat {bat} · fejl {f} · undslupne {e} · set {seen}/{total}"),
    "ph_preflight": _("Preflight", "Pregătire", "Przygotowanie", "Pré-voo", "Vorflugkontrolle", "Prevuelo", "Priprema",
                      "Предполетна подготовка", "Klargøring"),
    "ph_takeoff": _("Takeoff", "Decolare", "Start", "Descolagem", "Start", "Despegue", "Polijetanje", "Излитане", "Start"),
    "ph_transit": _("Takeoff / transit", "Decolare / tranzit", "Start / przelot", "Descolagem / trânsito", "Start / Anflug",
                    "Despegue / tránsito", "Polijetanje / prelet", "Излитане / преход", "Start / transit"),
    "ph_inspection": _("Fence inspection", "Inspecție gard", "Inspekcja ogrodzenia", "Inspeção da cerca", "Zaunkontrolle",
                       "Inspección de la cerca", "Pregled ograde", "Проверка на оградата", "Inspektion af hegnet"),
    "ph_return": _("Return", "Întoarcere", "Powrót", "Regresso", "Rückkehr", "Regreso", "Povratak", "Връщане", "Retur"),
    "ph_landing": _("Landing", "Aterizare", "Lądowanie", "Aterragem", "Landung", "Aterrizaje", "Slijetanje", "Кацане", "Landing"),
    "em_event": _("0 kV on the top wire", "0 kV pe firul de sus", "0 kV na górnym drucie", "0 kV no fio de cima",
                  "0 kV am oberen Draht", "0 kV en el hilo superior", "0 kV na gornjoj žici", "0 kV на горната жица",
                  "0 kV på den øverste tråd"),
    # ground/node.py (the ground station)
    "g_start": _("Ground station on · cameras: {cams} · fence alarm below {kv:.1f} kV",
                 "Stația de sol pornită · camere: {cams} · alarmă gard sub {kv:.1f} kV",
                 "Stacja naziemna włączona · kamery: {cams} · alarm ogrodzenia poniżej {kv:.1f} kV",
                 "Estação terrestre ligada · câmaras: {cams} · alarme da cerca abaixo de {kv:.1f} kV",
                 "Bodenstation an · Kameras: {cams} · Zaunalarm unter {kv:.1f} kV",
                 "Estación terrestre activa · cámaras: {cams} · alarma de la cerca por debajo de {kv:.1f} kV",
                 "Zemaljska stanica uključena · kamere: {cams} · alarm ograde ispod {kv:.1f} kV",
                 "Наземната станция е включена · камери: {cams} · аларма за оградата под {kv:.1f} kV",
                 "Jordstation tændt · kameraer: {cams} · hegnsalarm under {kv:.1f} kV"),
    "g_status": _("Ground station · {n} animals in view · fence {e:.1f} kV at the energizer, {end} at the far end",
                  "Stația de sol · {n} animale în cadru · gard {e:.1f} kV la energizator, {end} la capăt",
                  "Stacja naziemna · {n} zwierząt w kadrze · ogrodzenie {e:.1f} kV przy elektryzatorze, {end} na końcu",
                  "Estação terrestre · {n} animais à vista · cerca {e:.1f} kV no eletrificador, {end} no extremo",
                  "Bodenstation · {n} Tiere im Bild · Zaun {e:.1f} kV am Weidezaungerät, {end} am Ende",
                  "Estación terrestre · {n} animales a la vista · cerca {e:.1f} kV en el electrificador, {end} en el extremo",
                  "Zemaljska stanica · {n} životinja u kadru · ograda {e:.1f} kV kod električnog pastira, {end} na kraju",
                  "Наземна станция · {n} животни в кадър · ограда {e:.1f} kV при електропастира, {end} в края",
                  "Jordstation · {n} dyr i billedet · hegn {e:.1f} kV ved hegnsapparatet, {end} i den fjerne ende"),
    "g_outside": _("  GROUND   {id} ({species}) is outside the fence, {dist:.0f} m from the gate · seen by {cam}",
                   "  SOL      {id} ({species}) e în afara gardului, la {dist:.0f} m de poartă · văzut de {cam}",
                   "  ZIEMIA   {id} ({species}) jest poza ogrodzeniem, {dist:.0f} m od bramy · widziane przez {cam}",
                   "  SOLO     {id} ({species}) está fora da cerca, a {dist:.0f} m da porteira · visto pela {cam}",
                   "  BODEN    {id} ({species}) ist außerhalb des Zauns, {dist:.0f} m vom Tor · gesehen von: {cam}",
                   "  TIERRA   {id} ({species}) está fuera de la cerca, a {dist:.0f} m del portón · visto por la {cam}",
                   "  TLO      {id} ({species}) je izvan ograde, {dist:.0f} m od vrata · vidjela ga je {cam}",
                   "  ЗЕМЯ     {id} ({species}) е извън оградата, на {dist:.0f} м от портата · видяно от {cam}",
                   "  JORD     {id} ({species}) er uden for hegnet, {dist:.0f} m fra lågen · set af {cam}"),
    "g_gate": _("  GROUND   {id} went {dir} through the gate (iToF) · {n} animals out through the gate so far",
                "  SOL      {id} a ieșit {dir} pe poartă (iToF) · {n} animale ieșite pe poartă până acum",
                "  ZIEMIA   {id} przeszło przez bramę ({dir}, iToF) · dotąd wyszło przez bramę {n} zwierząt",
                "  SOLO     {id} passou pela porteira ({dir}, iToF) · {n} animais saíram pela porteira até agora",
                "  BODEN    {id} ging durch das Tor ({dir}, iToF) · bisher {n} Tiere durch das Tor hinaus",
                "  TIERRA   {id} pasó por el portón ({dir}, iToF) · {n} animales salieron por el portón hasta ahora",
                "  TLO      {id} je prošlo kroz vrata ({dir}, iToF) · dosad je kroz vrata izašlo {n} životinja",
                "  ЗЕМЯ     {id} мина през портата ({dir}, iToF) · досега през портата са излезли {n} животни",
                "  JORD     {id} gik gennem lågen ({dir}, iToF) · {n} dyr ude gennem lågen indtil nu"),
    "g_volt": _("  GROUND   Fence monitor: {wire} wire at the far end is at {kv:.1f} kV (alarm below {thr:.1f} kV)",
                "  SOL      Monitor gard: firul {wire} de la capătul gardului are {kv:.1f} kV (alarmă sub {thr:.1f} kV)",
                "  ZIEMIA   Monitor ogrodzenia: drut {wire} na końcu ma {kv:.1f} kV (alarm poniżej {thr:.1f} kV)",
                "  SOLO     Monitor da cerca: o fio {wire} no extremo está a {kv:.1f} kV (alarme abaixo de {thr:.1f} kV)",
                "  BODEN    Zaunmonitor: Draht {wire} am Ende hat {kv:.1f} kV (Alarm unter {thr:.1f} kV)",
                "  TIERRA   Monitor de la cerca: el hilo {wire} en el extremo tiene {kv:.1f} kV (alarma por debajo de {thr:.1f} kV)",
                "  TLO      Monitor ograde: {wire} žica na kraju ima {kv:.1f} kV (alarm ispod {thr:.1f} kV)",
                "  ЗЕМЯ     Монитор на оградата: {wire} жица в края е на {kv:.1f} kV (аларма под {thr:.1f} kV)",
                "  JORD     Hegnsmonitor: den {wire} tråd i den fjerne ende har {kv:.1f} kV (alarm under {thr:.1f} kV)"),
    "g_dispatch": _("  GROUND → AIR  Sending the drone to check: {reason}",
                    "  SOL → AER    Trimit drona să verifice: {reason}",
                    "  ZIEMIA → POWIETRZE  Wysyłam drona do sprawdzenia: {reason}",
                    "  SOLO → AR    A enviar o drone para verificar: {reason}",
                    "  BODEN → LUFT  Drohne wird zur Kontrolle geschickt: {reason}",
                    "  TIERRA → AIRE  Envío el dron a revisar: {reason}",
                    "  TLO → ZRAK   Šaljem dron da provjeri: {reason}",
                    "  ЗЕМЯ → ВЪЗДУХ  Изпращам дрона да провери: {reason}",
                    "  JORD → LUFT  Sender dronen ud for at tjekke: {reason}"),
    "g_busy": _("  GROUND   The drone is already out; the alert goes into its report.",
                "  SOL      Drona e deja în aer; alerta intră în raportul ei.",
                "  ZIEMIA   Dron jest już w powietrzu; alert trafi do jego raportu.",
                "  SOLO     O drone já está no ar; o alerta entra no relatório dele.",
                "  BODEN    Die Drohne ist schon unterwegs; der Alarm kommt in ihren Bericht.",
                "  TIERRA   El dron ya está en el aire; la alerta va a su informe.",
                "  TLO      Dron je već u zraku; upozorenje ide u njegovo izvješće.",
                "  ЗЕМЯ     Дронът вече е във въздуха; сигналът влиза в неговия доклад.",
                "  JORD     Dronen er allerede i luften; alarmen kommer med i dens rapport."),
    "guard_wait": _("Guard mode: the ground station watches; the drone takes off when it raises an alert. Ctrl+C stops everything.",
                    "Mod de pază: stația de sol veghează; drona decolează când apare o alertă. Ctrl+C oprește tot.",
                    "Tryb straży: stacja naziemna obserwuje; dron startuje, gdy podniesie ona alarm. Ctrl+C zatrzymuje wszystko.",
                    "Modo de guarda: a estação terrestre vigia; o drone descola quando ela dá um alerta. Ctrl+C para tudo.",
                    "Wachmodus: Die Bodenstation wacht; die Drohne startet, wenn sie Alarm gibt. Strg+C beendet alles.",
                    "Modo guardia: la estación terrestre vigila; el dron despega cuando ella da una alerta. Ctrl+C detiene todo.",
                    "Način straže: zemaljska stanica nadzire; dron polijeće kad ona digne uzbunu. Ctrl+C zaustavlja sve.",
                    "Режим охрана: наземната станция наблюдава; дронът излита, когато тя подаде сигнал. Ctrl+C спира всичко.",
                    "Vagttilstand: jordstationen holder øje; dronen letter, når den slår alarm. Ctrl+C stopper alt."),
    "trigger": _("Triggered by the ground station: {reason}", "Declanșat de stația de sol: {reason}",
                 "Wywołane przez stację naziemną: {reason}", "Acionado pela estação terrestre: {reason}",
                 "Ausgelöst von der Bodenstation: {reason}", "Activado por la estación terrestre: {reason}",
                 "Pokrenula zemaljska stanica: {reason}", "Задействано от наземната станция: {reason}",
                 "Udløst af jordstationen: {reason}"),
}

REASON = {
    "animal_outside": _("animal outside the fence near the gate", "animal în afara gardului lângă poartă",
                        "zwierzę poza ogrodzeniem przy bramie", "animal fora da cerca perto da porteira",
                        "Tier außerhalb des Zauns nahe dem Tor", "animal fuera de la cerca, junto al portón",
                        "životinja izvan ograde blizu vrata", "животно извън оградата близо до портата",
                        "dyr uden for hegnet nær lågen"),
    "gate_exit": _("animal left through the gate", "animal ieșit pe poartă", "zwierzę wyszło przez bramę",
                   "animal saiu pela porteira", "Tier ging durch das Tor hinaus", "animal salió por el portón",
                   "životinja je izašla kroz vrata", "животно излезе през портата", "dyr gik ud gennem lågen"),
    "voltage": _("fence voltage alarm", "alarmă de tensiune pe gard", "alarm napięcia ogrodzenia",
                 "alarme de tensão da cerca", "Zaunspannungsalarm", "alarma de tensión de la cerca", "alarm napona ograde",
                 "аларма за напрежението на оградата", "alarm for hegnsspænding"),
}
WIRE = {0: _("bottom", "de jos", "dolny", "de baixo", "unten", "inferior", "donja", "долната", "nederste"),
        1: _("top", "de sus", "górny", "de cima", "oben", "superior", "gornja", "горната", "øverste")}
DIRECTION = {"out": _("out", "afară", "na zewnątrz", "para fora", "hinaus", "hacia fuera", "van", "навън", "ud"),
             "in": _("in", "înăuntru", "do środka", "para dentro", "herein", "hacia dentro", "unutra", "навътре", "ind")}
CAM = {"rgb": _("RGB camera", "camera RGB", "kamera RGB", "câmara RGB", "RGB-Kamera", "cámara RGB", "RGB kamera",
                "RGB камера", "RGB-kamera"),
       "thermal": _("thermal camera", "camera termală", "kamera termowizyjna", "câmara térmica", "Wärmebildkamera",
                    "cámara térmica", "termalna kamera", "термокамера", "termisk kamera"),
       "depth": _("iToF", "iToF", "iToF", "iToF", "iToF", "iToF", "iToF", "iToF", "iToF")}

FAULT = {
    "wire_break": _("Broken wire (top strand)", "Sârmă ruptă (firul de sus)", "Zerwany drut (górny)",
                    "Fio partido (fio de cima)", "Gerissener Draht (oberer Draht)", "Hilo cortado (hilo superior)",
                    "Prekinuta žica (gornja)", "Скъсана жица (горната)", "Brudt tråd (øverste tråd)"),
    "post_down": _("Fallen post, wires on the ground", "Stâlp căzut, sârmele ating solul", "Przewrócony słupek, druty na ziemi",
                   "Poste caído, fios no chão", "Umgefallener Pfahl, Drähte am Boden", "Poste caído, hilos en el suelo",
                   "Srušen stup, žice na tlu", "Паднал стълб, жиците са на земята", "Væltet pæl, tråde på jorden"),
    "branch_short": _("Branch on the fence, short circuit", "Creangă pe gard, scurtcircuit", "Gałąź na ogrodzeniu, zwarcie",
                      "Ramo na cerca, curto-circuito", "Ast am Zaun, Kurzschluss", "Rama sobre la cerca, cortocircuito",
                      "Grana na ogradi, kratki spoj", "Клон върху оградата, късо съединение", "Gren på hegnet, kortslutning"),
}
FAULT_SHORT = {
    "wire_break": _("Broken wire", "Sârmă ruptă", "Zerwany drut", "Fio partido", "Draht gerissen", "Hilo cortado",
                    "Prekinuta žica", "Скъсана жица", "Brudt tråd"),
    "post_down": _("Fallen post", "Stâlp căzut", "Przewrócony słupek", "Poste caído", "Pfahl umgefallen", "Poste caído",
                   "Srušen stup", "Паднал стълб", "Væltet pæl"),
    "branch_short": _("Branch on fence", "Creangă pe gard", "Gałąź na ogrodzeniu", "Ramo na cerca", "Ast am Zaun",
                      "Rama en la cerca", "Grana na ogradi", "Клон на оградата", "Gren på hegnet"),
}
WHERE = {
    "post": _("post {post}", "stâlpul {post}", "słupek {post}", "poste {post}", "Pfahl {post}", "poste {post}",
              "stup {post}", "стълб {post}", "pæl {post}"),
    "segment": _("posts {a}–{b}", "între stâlpii {a}–{b}", "słupki {a}–{b}", "postes {a}–{b}", "Pfähle {a}–{b}",
                 "postes {a}–{b}", "stupovi {a}–{b}", "стълбове {a}–{b}", "pæle {a}–{b}"),
}
SPECIES = {"cow": _("cow", "vacă", "krowa", "vaca", "Kuh", "vaca", "krava", "крава", "ko"),
           "sheep": _("sheep", "oaie", "owca", "ovelha", "Schaf", "oveja", "ovca", "овца", "får")}

# sim/report.py (the HTML inspection report)
REPORT = {
    "html_title": _("Fence report", "Raport gard", "Raport ogrodzenia", "Relatório da cerca", "Zaunbericht",
                    "Informe de la cerca", "Izvješće o ogradi", "Доклад за оградата", "Hegnsrapport"),
    "title": _("Electric fence inspection report", "Raport inspecție gard electric",
               "Raport z inspekcji ogrodzenia elektrycznego", "Relatório de inspeção da cerca elétrica",
               "Bericht zur Kontrolle des Elektrozauns", "Informe de inspección de la cerca eléctrica",
               "Izvješće o pregledu električne ograde", "Доклад от проверката на електрическата ограда",
               "Rapport over inspektion af el-hegnet"),
    "origin": _("origin", "origine", "punkt odniesienia", "origem", "Ursprung", "origen", "ishodište", "начало", "udgangspunkt"),
    "language": _("Language", "Limba", "Język", "Idioma", "Sprache", "Idioma", "Jezik", "Език", "Sprog"),
    "faults": _("Faults", "Defecte", "Usterki", "Avarias", "Schäden", "Averías", "Kvarovi", "Повреди", "Fejl"),
    "escaped": _("Escaped animals", "Animale evadate", "Zbiegłe zwierzęta", "Animais fugidos", "Entlaufene Tiere",
                 "Animales escapados", "Odbjegle životinje", "Избягали животни", "Undslupne dyr"),
    "seen": _("Animals seen", "Animale văzute", "Widziane zwierzęta", "Animais vistos", "Gesehene Tiere", "Animales vistos",
              "Viđene životinje", "Видени животни", "Dyr set"),
    "time": _("Flight time", "Durată zbor", "Czas lotu", "Tempo de voo", "Flugzeit", "Tiempo de vuelo", "Trajanje leta",
              "Време на полета", "Flyvetid"),
    "dist": _("Distance", "Distanță", "Dystans", "Distância", "Strecke", "Distancia", "Udaljenost", "Разстояние", "Distance"),
    "fence": _("Fence inspected", "Gard inspectat", "Sprawdzone ogrodzenie", "Cerca inspecionada", "Kontrollierter Zaun",
               "Cerca inspeccionada", "Pregledana ograda", "Проверена ограда", "Inspiceret hegn"),
    "map": _("Map", "Harta", "Mapa", "Mapa", "Karte", "Mapa", "Karta", "Карта", "Kort"),
    "lg_fence": _("fence", "gard", "ogrodzenie", "cerca", "Zaun", "cerca", "ograda", "ограда", "hegn"),
    "lg_track": _("drone track", "traseul dronei", "trasa drona", "trajeto do drone", "Flugweg der Drohne",
                  "recorrido del dron", "putanja drona", "маршрут на дрона", "dronens rute"),
    "lg_fault": _("fault", "defect", "usterka", "avaria", "Schaden", "avería", "kvar", "повреда", "fejl"),
    "lg_animal": _("escaped animal", "animal evadat", "zbiegłe zwierzę", "animal fugido", "entlaufenes Tier",
                   "animal escapado", "odbjegla životinja", "избягало животно", "undsluppet dyr"),
    "faults_found": _("Faults found", "Defecte găsite", "Znalezione usterki", "Avarias encontradas", "Gefundene Schäden",
                      "Averías encontradas", "Pronađeni kvarovi", "Открити повреди", "Fundne fejl"),
    "what": _("What", "Ce", "Co", "O quê", "Was", "Qué", "Što", "Какво", "Hvad"),
    "where": _("Where", "Unde", "Gdzie", "Onde", "Wo", "Dónde", "Gdje", "Къде", "Hvor"),
    "from": _("From energizer", "De la energizator", "Od elektryzatora", "Desde o eletrificador", "Ab Weidezaungerät",
              "Desde el electrificador", "Od električnog pastira", "От електропастира", "Fra hegnsapparatet"),
    "prio": _("Priority", "Prioritate", "Priorytet", "Prioridade", "Priorität", "Prioridad", "Prioritet", "Приоритет", "Prioritet"),
    "outside": _("Animals outside the fence", "Animale în afara gardului", "Zwierzęta poza ogrodzeniem", "Animais fora da cerca",
                 "Tiere außerhalb des Zauns", "Animales fuera de la cerca", "Životinje izvan ograde", "Животни извън оградата",
                 "Dyr uden for hegnet"),
    "species": _("Species", "Specie", "Gatunek", "Espécie", "Art", "Especie", "Vrsta", "Вид", "Art"),
    "last": _("Last position", "Ultima poziție", "Ostatnia pozycja", "Última posição", "Letzte Position", "Última posición",
              "Posljednji položaj", "Последна позиция", "Sidste position"),
    "dfence": _("Distance to fence", "Distanță de gard", "Odległość od ogrodzenia", "Distância à cerca", "Abstand zum Zaun",
                "Distancia a la cerca", "Udaljenost od ograde", "Разстояние до оградата", "Afstand til hegnet"),
    "near": _("Near fault", "Lângă defectul", "Przy usterce", "Perto da avaria", "Nahe Schaden", "Junto a la avería",
              "Blizu kvara", "Близо до повреда", "Nær fejl"),
    "volt": _("Fence voltage (EM sensor, kV)", "Tensiunea gardului (senzor EM, kV)", "Napięcie ogrodzenia (czujnik EM, kV)",
              "Tensão da cerca (sensor EM, kV)", "Zaunspannung (EM-Sensor, kV)", "Tensión de la cerca (sensor EM, kV)",
              "Napon ograde (EM senzor, kV)", "Напрежение на оградата (EM сензор, kV)", "Hegnsspænding (EM-sensor, kV)"),
    "top": _("top wire", "fir sus", "górny drut", "fio de cima", "oberer Draht", "hilo superior", "gornja žica", "горна жица",
             "øverste tråd"),
    "bottom": _("bottom wire", "fir jos", "dolny drut", "fio de baixo", "unterer Draht", "hilo inferior", "donja žica",
                "долна жица", "nederste tråd"),
    "thr": _("4 kV threshold", "prag 4 kV", "próg 4 kV", "limiar de 4 kV", "Schwelle 4 kV", "umbral de 4 kV", "prag od 4 kV",
             "праг 4 kV", "tærskel 4 kV"),
    "no_faults": _("No faults found.", "Niciun defect găsit.", "Nie znaleziono usterek.", "Nenhuma avaria encontrada.",
                   "Keine Schäden gefunden.", "No se encontraron averías.", "Nisu pronađeni kvarovi.", "Не са открити повреди.",
                   "Ingen fejl fundet."),
    "no_animals": _("No animals outside the fence.", "Niciun animal în afara gardului.", "Brak zwierząt poza ogrodzeniem.",
                    "Nenhum animal fora da cerca.", "Keine Tiere außerhalb des Zauns.", "Ningún animal fuera de la cerca.",
                    "Nema životinja izvan ograde.", "Няма животни извън оградата.", "Ingen dyr uden for hegnet."),
    "gate": _("gate", "poartă", "brama", "porteira", "Tor", "portón", "vrata", "порта", "låge"),
    "urgent": _("Urgent", "Urgent", "Pilne", "Urgente", "Dringend", "Urgente", "Hitno", "Спешно", "Haster"),
    "today": _("Today", "Azi", "Dziś", "Hoje", "Heute", "Hoy", "Danas", "Днес", "I dag"),
    "note": _("{n} animals never entered the camera view: a pass along the fence sees about 15–20 m into the paddock. "
              "Counting the whole herd needs an extra grid flight over the middle of the pasture. Detections in the "
              "simulation use the true positions from Gazebo; on the real drone they come from a vision model on the camera images.",
              "{n} animale nu au intrat în câmpul camerei: un tur pe lângă gard vede cam 15–20 m spre interior. "
              "Pentru numărarea completă a turmei adaugă un zbor în grilă peste mijlocul pășunii. Detecțiile din simulare "
              "folosesc pozițiile reale din Gazebo; pe drona reală vin dintr-un model de detecție pe imaginea camerei.",
              "{n} zwierząt nie znalazło się w polu widzenia kamery: przelot wzdłuż ogrodzenia widzi około 15–20 m w głąb "
              "pastwiska. Policzenie całego stada wymaga dodatkowego lotu po siatce nad środkiem pastwiska. Wykrycia w symulacji "
              "korzystają z prawdziwych pozycji z Gazebo; na prawdziwym dronie pochodzą z modelu wizyjnego na obrazie z kamery.",
              "{n} animais nunca entraram no campo de visão da câmara: uma passagem ao longo da cerca vê cerca de 15–20 m "
              "para dentro do pasto. Contar todo o rebanho exige um voo extra em grelha sobre o meio do pasto. Na simulação, "
              "as deteções usam as posições reais do Gazebo; no drone real vêm de um modelo de visão aplicado às imagens da câmara.",
              "{n} Tiere kamen nie ins Kamerabild: Ein Flug entlang des Zauns sieht etwa 15–20 m in die Weide hinein. Um die "
              "ganze Herde zu zählen, braucht es einen zusätzlichen Rasterflug über die Mitte der Weide. In der Simulation "
              "nutzen die Erkennungen die wahren Positionen aus Gazebo; auf der echten Drohne kommen sie von einem "
              "Bildverarbeitungsmodell auf den Kamerabildern.",
              "{n} animales nunca entraron en el campo de la cámara: una pasada a lo largo de la cerca ve unos 15–20 m hacia "
              "dentro del potrero. Para contar todo el rebaño hace falta un vuelo adicional en cuadrícula sobre el centro del "
              "campo. En la simulación, las detecciones usan las posiciones reales de Gazebo; en el dron real vienen de un "
              "modelo de visión sobre las imágenes de la cámara.",
              "{n} životinja nikad nije ušlo u kadar kamere: prelet uz ogradu vidi oko 15–20 m u pašnjak. Za brojanje cijelog "
              "stada potreban je dodatni let po mreži iznad sredine pašnjaka. U simulaciji detekcije koriste stvarne položaje "
              "iz Gazeba; na pravom dronu dolaze iz modela računalnog vida na slikama kamere.",
              "{n} животни не влязоха в обхвата на камерата: полет покрай оградата вижда около 15–20 м навътре в пасището. "
              "За да се преброи цялото стадо, е нужен допълнителен полет по мрежа над средата на пасището. В симулацията "
              "откриванията използват истинските позиции от Gazebo; на истинския дрон идват от модел за компютърно зрение "
              "върху изображенията от камерата.",
              "{n} dyr kom aldrig ind i kameraets synsfelt: en tur langs hegnet ser omkring 15–20 m ind på marken. For at "
              "tælle hele flokken kræves en ekstra gitterflyvning over midten af marken. I simuleringen bruger detektionerne "
              "de sande positioner fra Gazebo; på den rigtige drone kommer de fra en billedgenkendelsesmodel på kamerabillederne."),
}


def pick(entry, lang=None):
    """The text of an entry in `lang` (default: the chosen language), falling back to English.

    Accepts the nine-language dicts above and the older (en, ro) pairs."""
    lang = lang or LANG
    if isinstance(entry, dict):
        return entry.get(lang) or entry.get("en", "")
    if isinstance(entry, (tuple, list)):
        return entry[1] if lang == "ro" and len(entry) > 1 else entry[0]
    return entry


def t(key, lang=None, **kw):
    return pick(MSG[key], lang).format(**kw)


def both(entry, **kw):
    """{"en": ..., "ro": ..., "pl": ..., ...} for JSON fields a person reads (the name predates the other languages)."""
    return {lang: pick(entry, lang).format(**kw) for lang in LANGS}


def is_text(v):
    """True for a translation entry or a multi-language JSON text field."""
    return (isinstance(v, dict) and "en" in v and all(isinstance(x, str) for x in v.values())) or \
           (isinstance(v, tuple) and len(v) == 2 and all(isinstance(x, str) for x in v))
