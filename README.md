# Gardian X500

Simulare Gazebo pentru proiectul de inspecție a gardului electric cu drona Holybro X500 (PX4).
Drona zboară singură pe lângă gard, găsește defectele (sârmă ruptă, stâlp căzut, creangă pe gard),
măsoară tensiunea pe fire și vede animalele ieșite din țarc. La final scoate un raport cu hartă și GPS.

## Cum intri în simulare

**Dublu-click pe `Gardian Sim.command` de pe Desktop.** Atât.

Sau din terminal:

```bash
cd ~/Desktop/Gardian-X500
./start.sh            # zbor automat de inspecție + raport (implicit)
./start.sh manual     # doar simularea, consola PX4 (pxh>) rămâne la tine
./start.sh fara-gui   # fără fereastra Gazebo (cel mai ușor pentru laptop)
./start.sh misiune    # doar zborul, pe o simulare deja pornită
./stop.sh             # oprește tot (și simulări rămase agățate)
```

După fiecare zbor simularea rămâne pornită: **Enter** = zbor nou, **Ctrl+C** = închide tot.

## Ce vezi

- **Fereastra Gazebo**: pășunea, gardul cu 2 fire, cele 3 defecte, 24 de animale (3 evadate), grajdul, platforma H.
  Camera urmărește lin drona. Linia galbenă e traseul planificat. Stâlpii portocalii = defecte găsite, cei roșii = animale evadate.
- **Panoul „Camera dronei”**: ce vede camera de inspecție (640×400, înclinată 55° în jos).
- **Terminalul**: faza zborului, altitudine, viteză, baterie și fiecare detecție cu coordonate GPS.
- **Raportul** (`reports/raport_*.html`, se deschide singur la final): hartă, tabel defecte, animale evadate, graficul de tensiune.

## Cum schimbi scenariul

Totul e în `fence.json`: forma gardului, unde sunt defectele, câte animale, care au evadat,
altitudinea și viteza zborului, unghiul camerei. Salvezi și pornești din nou; lumea se regenerează singură.

## Cum e făcut

| Fișier | Ce face |
|---|---|
| `fence.json` | configurația pășunii (o singură sursă pentru lume, misiune și detector) |
| `sim/gen_world.py` | generează `worlds/pasture.sdf` pentru Gazebo |
| `models/x500_fence` | X500 din PX4 + camera de inspecție, mai ușoară decât camera PX4 standard |
| `sim/mission.py` | MAVLink (pymavlink): setează PX4 pentru zbor lin, urcă misiunea, armează, detectează, scrie raportul |
| `sim/director.py` | Gazebo (gz-transport): mișcă animalele, camera urmăritoare, marcajele 3D |
| `sim/report.py` | raportul HTML |
| `config/gui.config` | fereastra Gazebo (fără pluginuri grele, ca să meargă fluid) |

Folosește PX4 din `~/PX4-Autopilot` (deja compilat) și Gazebo Harmonic din mediul lui pixi.
Nu modifică nimic în PX4. Altă locație: `PX4_DIR=/cale/PX4-Autopilot ./start.sh`.

**Detectorul e simulat**: folosește pozițiile reale din Gazebo ca să arate ce ar raporta camera și senzorul EM.
Pe drona reală, `Detector` din `sim/mission.py` se înlocuiește cu un model de detecție pe imaginea camerei,
iar senzorul EM cu o bobină care măsoară pulsurile gardului.

## Dacă ceva nu merge

Logurile sunt în `run/`: `mission.log`, `gz_server.log`, `px4.log`, `director.log`.
Cele două erori „Unable to load Ogre Plugin” din `gz_server.log` sunt normale pe Mac: camera randează oricum (Metal).
`./stop.sh` curăță orice proces rămas, apoi pornești din nou.
