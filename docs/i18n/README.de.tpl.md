# Querra Fence · Gardian X500

{{LANGBAR}}

<img src="docs/assets/icon.svg" width="72" align="right" alt="Querra-Fence-Icon">

**Sicherer Zaun: Schützen Sie Ihre Tiere vor Raubtieren.** Projektseite mit den Sensoren und der Roadmap:
**[cosminbmemetea.github.io/querra-fence](https://cosminbmemetea.github.io/querra-fence/?lang=de)**

Autonome Kontrolle von Elektrozäunen mit einer PX4 **Holybro X500**, durchgehend simuliert in **Gazebo Harmonic**.
Die Drohne fliegt selbstständig die Zaunlinie ab, findet Schäden (gerissener Draht, umgefallener Pfahl, ein Ast, der
die Drähte kurzschließt), misst, wo der Zaun Spannung verliert, erkennt Tiere, die aus der Koppel ausgebrochen sind,
landet und schreibt einen Bericht mit den GPS-Koordinaten jedes Fundes.

Die ausführliche Dokumentation in `docs/` ist auf Englisch.

![Die Weide nach einem Kontrollflug: gelbe Route, orange Strahlen an Schäden, rote an ausgebrochenen Tieren](docs/media/result-overview.jpg)

<p>
  <img src="docs/media/dronecam.gif" width="49%" alt="Die Kontrollkamera fliegt am gerissenen Draht vorbei, die ausgebrochenen Kühe sind markiert">
  <img src="docs/media/takeoff.gif" width="49%" alt="X500 startet von seinem Landeplatz neben dem Zaun">
</p>

## Feld-Steuerpanel

Der Jetson betreibt ein Web-Dashboard auf Port 8080 (`http://mmx-desktop.local:8080`) für ein Handy im Hotspot oder
einen Laptop. Es zeigt beide Kameras live, die Ziele des LD2450-Radars und den GPS-Fix und startet und stoppt die
Datenerfassung mit dem Zaundetektor v0.3. Es funktioniert offline, auf Englisch oder Polnisch. Code und Architektur
liegen in [`jetson/panel/`](jetson/panel/). Die Radarkarte hat eine abklingende Belegungs-Heatmap (an/aus und Löschen),
und die ROS-2-Karte startet und stoppt ROS 2, zeigt die Topic-Raten und zeichnet Bags auf.

<img src="docs/img/panel-demo.gif" width="960" alt="QUERRA-Panel: Live-Kameras, Radar-Heatmap, GPS (Position unscharf), Start und Stopp der Datenerfassung, ROS-2-Karte, Englisch zu Polnisch">

<img src="docs/img/panel-demo-phone.gif" width="300" alt="QUERRA-Panel auf einem Handy"> <img src="docs/img/panel-desktop.png" width="560" alt="QUERRA-Panel am Desktop">

Die GPS-Koordinaten sind in diesen Aufnahmen unscharf gemacht.

Desktop-Launcher: `sudo apt install ./querra-fence-panel_0.6.0_arm64.deb` legt ein **Querra Fence**-Icon ins Dock des
Jetson, das das Panel wieder öffnet (und es bei Bedarf startet). Siehe [packaging/deb/](packaging/deb/).

## ROS 2 (Phasen 1–3)

Die Sensoren des Jetson sind auch ROS-2-Humble-Topics. Die Knoten laufen in Docker auf der SSD und sind Clients der
Dienste, denen die Hardware gehört: Kameras vom Panel-Hub, GPS von gpsd, Radar vom Dienst ld2450-radar. Sie
veröffentlichen `sensor_msgs`-Bilder, `NavSatFix`, Radarziele, `PointCloud2` und Marker. Aufzeichnungen sind
rosbag2-MCAP-Dateien, und Foxglove verbindet sich mit `ws://<jetson>:8765`. Nutzen Sie die ROS-2-Karte im Panel oder
`ros2/ros.sh`. Details stehen in [docs/ros2.md](docs/ros2.md).

Phase 2 bringt den Zaundetektor nach ROS 2: `fence_detector` führt die TensorRT-FP16-Engine des Modells YOLO11n v0.3
auf der Jetson-GPU aus (etwa 15 Hz, 20–30 ms pro Bild von JPEG bis zu den Boxen) und veröffentlicht
`vision_msgs/Detection2DArray` sowie ein annotiertes Bild. `alert_confirm` macht aus Erkennungen nur dann
`/fence/alerts`, wenn 5 der letzten 8 Bilder am Boden auf 5 m übereinstimmen. `./ros.sh demo` (oder **Demo** im Panel)
spielt eine aufgezeichnete Gazebo-Mission durch die ganze Kette ab; `./ros.sh demo tcp://<mac>:5601` nutzt die
Live-Simulation. Foxglove-Layout: [`ros2/foxglove/querra-layout.json`](ros2/foxglove/querra-layout.json).
Ablauf für Präsentationen: [docs/interview-demo.md](docs/interview-demo.md).

Phase 3 bindet PX4 selbst an: `./ros.sh demo tcp://<mac>:5601 px4:=true` startet einen micro-ROS-Agenten auf UDP 8888.
Der uXRCE-DDS-Client von PX4 veröffentlicht dort `/fmu/out/*`, und `px4_pose` macht aus Position und Kurs der Drohne
selbst `/px4/telemetry`, womit dann die Alarme verortet werden. Auf dem Mac leitet `tools/uxrce_relay.py <jetson>` den
Client von PX4 SITL an den Jetson weiter, an PX4 ändert sich also nichts. In einem simulierten Flug stimmte die
PX4-Pose mit der Telemetrie des Simulators auf 0,6 m (Median) überein, und die drei echten Schäden wurden 2,4 m, 3,0 m
und 4,2 m von ihrer wahren Position gemeldet. Mit `refly:=true` übernimmt der Jetson nach der Kontrollrunde: Er schaltet
PX4 in OFFBOARD, fliegt tief über jeden bestätigten Schaden, um ihn aus der Nähe anzusehen, und gibt mit Return zurück.
In SITL hat der ganze Flug funktioniert: 8 Anflüge, dann Rückkehr und Landung. Die Nahprüfung ist noch nicht
zuverlässig, weil der Detektor in 12 m und nicht in 6 m Höhe trainiert wurde. Details und die ehrlichen Zahlen:
[docs/ros2.md](docs/ros2.md#phase-3-px4-over-uxrce-dds).

{{MERMAID_ROS}}

## Was ein Flug macht

| Schritt | Was passiert |
|---|---|
| Planen | Das Zaunpolygon aus `fence.json` wird zu einer geglätteten Route 2,5 m außerhalb des Drahts, mit 56 Wegpunkten |
| Fliegen | PX4 startet auf 12 m, fliegt die 414 m Zaun mit 5 m/s ab, kehrt zurück und landet (etwa 2,5 min) |
| Erkennen | Eine geneigte Kontrollkamera und ein simulierter EM-Sensor melden Schäden, Spannungsverlust und Tiere außerhalb des Polygons |
| Bericht | `reports/raport_*.json` für Software, `raport_*.html` mit Karte, Tabellen und Spannungsprofil |

Ergebnis des Beispielflugs in [`docs/sample-report`](docs/sample-report/sample-report.html):
**3 von 3 Schäden** gefunden, **3 von 3 ausgebrochenen Tieren** gefunden, Spannung am oberen Draht direkt nach dem Riss
verloren, **9 von 24 Tieren** gezählt (ein Flug entlang des Zauns sieht nur 10 bis 15 m in die Koppel hinein).

## Demo

**Kontrollkamera.** Was die Drohne aus 12 m sieht, mit den Erkennungen im Bild.

<p>
  <img src="docs/media/dronecam-F1.jpg" width="49%" alt="Gerissener oberer Draht, von der Drohne aus gesehen">
  <img src="docs/media/dronecam-V13.jpg" width="49%" alt="Ausgebrochene Kuh neben dem gerissenen Draht">
</p>

**Die drei Schäden am Boden.**

![Gerissener oberer Draht, umgefallener Pfahl, Ast auf den Drähten](docs/media/faults.jpg)

**Vor dem Start.** Die X500 auf ihrem Landeplatz und das Weidezaungerät am Anfang des Zauns.

<p>
  <img src="docs/media/x500-on-pad.jpg" width="49%" alt="X500 auf dem Landeplatz">
  <img src="docs/media/fence-energizer.jpg" width="49%" alt="Weidezaungerät und die ersten Zaunpfähle">
</p>

**Der Bericht.** Er öffnet sich in der Sprache, in der der Flug lief, und hat ein Menü mit neun Sprachen: EN, RO, PL,
PT, DE, ES, HR, BG, DA.

<img src="docs/media/report.png" width="640" alt="Kontrollbericht mit Karte, Schadenstabelle, ausgebrochenen Tieren und Spannungsdiagramm">

## Schnellstart

Getestet auf einem Mac mit Apple Silicon (M2, 8 GB) mit PX4 `main` (v1.18 beta) und Gazebo Harmonic 8.10.

1. PX4 einmal für die Simulation bauen, mit dem Gazebo-Setup von PX4:

   {{BASH_PX4}}

2. Die Kontrolle starten:

   {{BASH_RUN}}

   Gazebo öffnet sich, die Drohne fliegt, die Erkennungen erscheinen im Terminal, und der Bericht öffnet sich im
   Browser. **Enter** für einen weiteren Flug, **Strg+C** schließt alles.

| Befehl | Was er macht |
|---|---|
| `./start.sh` | Vollautomatischer Kontrollflug mit Bericht (Standard) |
| `./start.sh manual` | Nur die Simulation; die PX4-Konsole (`pxh>`) bleibt für eigene Befehle im Terminal |
| `./start.sh headless` | Wie der Standard ohne Gazebo-Fenster; am leichtesten auf einem Laptop |
| `./start.sh mission` | Nur der Kontrollflug, in einer bereits laufenden Simulation |
| `./start.sh demo` | Ein gefilmter Flug, der alles in `docs/media` neu erzeugt |
| `./start.sh guard` | Boden + Luft: eine Bodenstation am Tor (RGB, Wärmebild, iToF, Zaunmonitor) schickt die Drohne, wenn sie ein Problem sieht; ihre Kameras sind RTSP-Streams ([Details](docs/ground-station.md)) |
| `./stop.sh` | Beendet alle Prozesse, auch Reste eines abgestürzten Laufs |
| `tools/install_launcher.sh` | Legt ein per Doppelklick startbares `Gardian Sim.command` auf den Schreibtisch |

Hängen Sie `--lang <Code>` an einen beliebigen Modus an (oder setzen Sie `GARDIAN_LANG`), um Terminal und Bericht in
einer anderen Sprache zu bekommen: `en` (Standard), `ro`, `pl`, `pt`, `de`, `es`, `hr`, `bg` oder `da`. Die Sprache des
Berichts lässt sich auch nachträglich umstellen. PX4 an anderer Stelle: `PX4_DIR=/pfad/zu/PX4-Autopilot ./start.sh`.
Im PX4-Verzeichnis wird nichts verändert.

## Bodenstation + Drohne

`./start.sh guard` fügt eine Bodenstation im Jetson-Stil auf einem Mast am Tor hinzu: RGB- und Wärmebildkamera am Mast,
ein iToF-Tiefensensor am Torpfosten und ein Zaunmonitor am anderen Ende des Drahts. Sie wacht ständig und schickt die
Drohne, wenn ein Tier durch das Tor geht oder die Zaunspannung abfällt. Ihre Kameras werden als RTSP-Streams
veröffentlicht, sodass ein echter Jetson seine Modelle auf der Simulation laufen lassen kann, bevor er ins Feld geht.
Siehe [docs/ground-station.md](docs/ground-station.md).

**Fragen Sie den Jetson, was er sieht.** `brain/server.py` läuft auf dem Jetson: Es nimmt die RTSP-Bilder und den
Live-Zustand (`sim/state_server.py`), beantwortet getippte Fragen mit einem lokalen Bild-Sprach-Modell (Ollama), das
sich auf Sensordaten stützt, und spricht die Antwort (Piper). Einrichtung und Ablauf: [docs/jetson-brain.md](docs/jetson-brain.md).

![Simulierte Streams der Bodenstation](docs/media/ground-cameras.png)

## Echter Sensor: LD2450-Radar am Jetson

Die erste echte Hardware der Bodenstation ist ein HiLink LD2450, ein 24-GHz-mmWave-Radar, das bis zu 3 Ziele verfolgt.
Es ist über einen USB-Seriell-Adapter CH340 mit dem Jetson verbunden.
`radar/` liest es aus und stellt eine Live-Radarseite bereit:
- Ziele auf einem ±60°-Fächer, mit flüssiger Bewegung, Spuren und einer Heatmap;
- Entfernung, Winkel, Geschwindigkeit und Bewegungsart jedes Ziels;
- ein 60-Sekunden-Entfernungsdiagramm und ein Aktivitätsprotokoll.

Es ist als Debian-Paket verpackt, das als Systemdienst läuft und ein App-Icon auf den Desktop legt:

```bash
sudo apt install ./ld2450-radar_1.0.1_all.deb     # von der Release-Seite
# dann "LD2450 Radar" öffnen, oder http://<jetson>:8077 von jedem Gerät im Netzwerk
```

Details, Verkabelung und die JSON/SSE-API stehen in [radar/README.md](radar/README.md).

![LD2450-Radar auf dem Jetson](docs/media/ld2450-radar.png)

## So funktioniert es

{{MERMAID_HOW}}

| Pfad | Aufgabe |
|---|---|
| `fence.json` | Einzige Quelle der Wahrheit: Zaunpolygon, Pfähle, Schäden, Herde, ausgebrochene Tiere, Flug- und Kameraeinstellungen |
| `sim/gen_world.py` | Erzeugt die Gazebo-Welt: Zweidrahtzaun mit isoliertem Tor und Weidezaungerät, Schäden, Bäume, Stall, Herde |
| `models/x500_fence` | Die X500 von PX4 plus eine Kontrollkamera mit 640×400 bei 15 fps, 55° nach unten geneigt, leichter als die serienmäßige 1280×960 |
| `sim/mission.py` | pymavlink: PX4-Parameter für ruhigen Flug, Missions-Upload, Scharfschalten als GCS, Detektor, Bericht |
| `sim/director.py` | Gazebo-Python: grasende und wandernde Tiere, Verfolgerkamera, geplante Route und Erkennungsmarker |
| `sim/geo.py` | Gemeinsame Geometrie: Pfähle, Schadensorte, Außenroute, Punkt im Polygon, lokal ⇄ GPS, Spannungsmodell |
| `sim/report.py` | HTML-Bericht mit SVG-Karte, Spannungsprofil und einem Sprachmenü (neun Sprachen) |
| `sim/i18n.py` | Jede Meldung, die ein Mensch liest, in neun Sprachen (EN, RO, PL, PT, DE, ES, HR, BG, DA) |
| `tools/` | Demo-Aufnahme, Medien-Generator, Szenario-Rekorder, Desktop-Starter |
| `ground/`, `brain/` | Simulierter Knoten der Bodenstation; das Jetson-Gehirn, das Fragen dazu beantwortet, was es sieht |
| `radar/` | LD2450-mmWave-Radar am Jetson: Live-Webansicht und Debian-Paket |

## Konfiguration

Das ganze Szenario steht in `fence.json`. Ändern und neu starten; die Welt wird neu erzeugt.

{{JSON}}

Koordinaten sind lokale Meter (x nach Osten, y nach Norden) um `origin`, das die GPS-Position der Weide festlegt.

## Zaundetektor auf dem Jetson (YOLO11n)

Die Simulation trainiert jetzt die echte Wahrnehmung der Drohne. `tools/make_dataset.py` rendert zufällige Höfe in
Gazebo und beschriftet jedes Bild aus der bekannten 3D-Geometrie: 7 Klassen, ohne Handarbeit. Ein auf diesen Bildern
trainiertes YOLO11n läuft als TensorRT-FP16-Engine auf einem Jetson Orin Nano. Der Jetson liest die simulierte
Drohnenkamera über das LAN (`tools/cam_stream.py`), während PX4 die Mission fliegt, und protokolliert jede Erkennung mit GPS.

| Modell | Val mAP50 | Auf dem Jetson (simulierte Mission) | Release |
|---|---|---|---|
| v0.1 · Checkpoint aus Epoche 2 | 0.72 | gerissener Draht F1 gefunden (0.78); schwach beim umgefallenen Pfahl | `model-v0.1` |
| v0.2 · 25 Epochen | 0.921 | 13.3 fps; F1, F2, F3 alle gefunden (0.94 / 0.96 / 0.84); 385 Bilder mit falschem gerissenem Draht | `model-v0.2` |
| v0.3 · mit gezielten Daten feinjustiert | 0.916 (Testset 0.912) | `wire_break` Test-mAP50 0.58 → 0.68; mit GPS-Bestätigung 5 von 8 Fehlalarme 33 → 6, alle Schäden gefunden | `model-v0.3` |

![v0.2 auf dem Jetson: gerissener Draht, umgefallener Pfahl, Ast und der falsche gerissene Draht, den v0.3 reduziert](docs/img/v0.2-jetson-faults.jpg)

- [Trainingsprotokoll](docs/retraining-log.md): was jede Version verpasst hat und was sich geändert hat.
- [Model Card](docs/model-card.md): Daten, Metriken, Grenzen und Reproduktion.
- [Jetson-Integration](docs/jetson-integration.md): die Kameraquelle `sim:`, der Detektor und der Feldmodus in querra-scout.

## Simulation und Wirklichkeit

Der Flug ist echter PX4-Code: dieselbe Mission, dieselben Parameter und MAVLink-Befehle würden eine echte X500 steuern.
Die Wahrnehmung ist noch nicht echt, und die Boxen in den Demo-Bildern sagen das:

- **Die Erkennung** in `sim/mission.py` nutzt noch die wahren Positionen aus Gazebo, um zu zeigen, was die Kamera
  melden würde. Das Bildmodell, das sie ersetzt, läuft bereits auf dem Jetson (siehe [Zaundetektor](#zaundetektor-auf-dem-jetson-yolo11n)).
- **Die Zaunspannung** kommt aus einem einfachen Stromkreismodell entlang des Zauns. Eine echte Version braucht einen
  Sensor, der die Impulse des Weidezaungeräts aus der Luft auffängt, oder feste Spannungsmonitore am Zaun.
- **Abdeckung**: Aus 12 m sieht die Kamera etwa 10 bis 15 m zu jeder Seite. Für die ganze Herde braucht es einen zusätzlichen Rasterflug.

## Roadmap

1. Einen Detektor auf dem Kamerastream aus Gazebo trainieren, dann auf echten Zaunfotos (gerissener Draht, schiefer
   Pfahl, Bewuchs, Rinder, Schafe)
2. Den Zaun aus einer GPS-Begehung oder einer KML/GeoJSON-Datei importieren statt aus lokalen Metern
3. Gimbal und Wärmebildkamera für Nachtkontrollen
4. Rasterflug, um die ganze Herde zu zählen
5. Alarme aufs Handy und eine Karte offener Schäden
6. Das LD2450-Radar als echter Torzähler im Wachmodus, statt des simulierten iToF-Sensors
7. Hardware: X500 V2, Pixhawk, Raspberry Pi 5 oder Jetson als Bordrechner, mit demselben MAVLink-Missionscode

Die nächtliche Raubtierwache (Wärmebildkamera und Radar am Tor) ist geplant; siehe die
[Projektseite](https://cosminbmemetea.github.io/querra-fence/?lang=de#roadmap).

## Hinweise

- Die Simulation spricht neun Sprachen (`--lang pl`, `--lang de`, …). Logs sind immer auf Englisch. In den JSON-Daten
  wird Text, den ein Mensch liest, in allen Sprachen gespeichert.
- Die Demo-Bilder in `docs/media` haben derzeit rumänische Beschriftungen; `./start.sh demo` erzeugt sie auf Englisch neu.
- Linux ist noch nicht getestet. Die Skripte erwarten die macOS-Gazebo-Umgebung von PX4 (`Tools/setup/macos/.pixi`) und
  öffnen den Bericht mit `open`.
- Die Logs jedes Laufs liegen in `run/`: `mission.log`, `px4.log`, `gz_server.log`, `director.log`.
  Die zwei Fehler „Unable to load Ogre Plugin“ in `gz_server.log` sind unter macOS normal; die Kamera rendert trotzdem.
