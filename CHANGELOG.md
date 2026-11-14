# Schimbări

## v0.1.0 · 2026-11-14

Prima versiune: un zbor complet de inspecție a gardului electric, în simulare.

### Simulare
- Lumea pășunii generată din `fence.json`: gard electric de 414 m cu două fire pe 75 de stâlpi, poartă izolată,
  energizator, grajd, copaci, platformă de aterizare
- Trei tipuri de defecte: firul de sus rupt (capete atârnate), stâlp căzut cu firele pe sol, creangă peste fire
- Turmă de 14 vaci și 10 oi care pasc și se plimbă; trei dintre ele au evadat lângă defecte
- Holybro X500 din PX4 cu o cameră de inspecție mai ușoară (640×400, 15 fps, înclinată 55° în jos)

### Misiune
- Traseu pe lângă gard, la 2,5 m în exterior, cu colțuri rotunjite: 56 de puncte la 12 m și 5 m/s
- PX4 reglat pentru zbor lin (accelerație, jerk, viteză de rotire, altitudini RTL); armează în cam 2 s pentru că se prezintă ca stație de sol
- Detector de cameră simulat pentru defecte și animale din afara gardului, cu GPS pentru fiecare
- Profil de tensiune EM simulat pe ambele fire, care arată unde firul de sus rămâne fără curent
- Raport JSON și HTML: hartă, defecte cu prioritate, animale evadate, grafic de tensiune

### Unelte
- `start.sh` cu modurile: zbor automat, consolă PX4 manuală, fără fereastră, doar misiune, demo filmat
- `stop.sh` oprește toate procesele; `tools/install_launcher.sh` pune pe Desktop un launcher cu dublu-click
- `start.sh demo` filmează imaginile pentru README: capturi Gazebo, GIF cu decolarea, imagini adnotate din camera dronei, captura raportului
