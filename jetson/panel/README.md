# QUERRA field panel (Jetson)

A snapshot of `~/querra-scout-20261107/panel/` on the Jetson. querra-scout is not in this repository. The panel is a
single page for the field: start and stop field mode from a phone or a laptop.

- **Stack:** Python standard library only (`http.server`), one HTML file, port 8080 on all interfaces.
- **Open to everyone on the network:** live status (frames, fps, GPS fix and position, last detections, confirmed
  alerts, SSD and root free space, CPU and GPU temperature, power mode, uptime) and the latest annotated frame.
- **Needs the PIN** from `config.json`, which is created on first start and is not in git:
  - start and stop field mode. Stop runs `field-stop.sh` and the page says when it is safe to cut the power.
  - "Pornire automată la boot": a user crontab line tagged `# querra-field`, off by default
  - querra-vision on and off
  - choosing the v0.2 or v0.3 engine. This edits `field.sh` with a backup, and only while field mode is stopped.
  - downloading a run as a streamed `.tar.gz`
  - safe shutdown. Without passwordless poweroff the page shows `sudo poweroff` instead.
- **Five wrong PINs** lock actions for 60 s.
- **The panel starts at boot** from a user crontab line tagged `# querra-panel`. It never starts field capture by
  itself.

```bash
cd ~/querra-scout-20261107/panel && ./restart.sh     # (re)start the panel; field mode is not touched
```
