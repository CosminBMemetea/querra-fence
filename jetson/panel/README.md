# QUERRA Fence panel v2 (Jetson)

<img src="../../docs/img/panel-demo.gif" width="900" alt="QUERRA panel demo (GPS position blurred)">

A snapshot of `~/querra-scout-20261107/panel/` on the Jetson. querra-scout is not in this repository. One page for the
field, in English or Polish (EN | PL switch, remembered by the browser), for a phone on the hotspot or a laptop.


- **Stack:** Python standard library `http.server` plus the GStreamer, OpenCV and NumPy that JetPack already ships.
  One HTML file, no CDN, so it works offline on a phone hotspot. Port 8080 on all interfaces.
- **No PIN** by default (`"require_pin": false` in `config.json`; set it to `true` to bring the PIN back).

## Who owns what

`hub.py` makes the panel the single owner of the devices, so the live view and data collection never fight over them:

| Device | Owner | Panel reads it from |
| --- | --- | --- |
| USB Arducam (`/dev/video-uvc-rgb`, MJPEG 1280x720) | panel hub, GStreamer, opened on demand | in process |
| CSI IMX219 (Argus, `nvarguscamerasrc`) | panel hub, hardware scaled to 640x360 | in process |
| GPS u-blox (`/dev/ttyACM0`) | `gpsd` | `gpsd` JSON on port 2947 |
| LD2450 radar (`/dev/ttyUSB0`) | `ld2450-radar` service | `/events` SSE and `/state` on port 8077 |

- **Live view:** `/stream/usb.mjpg` and `/stream/csi.mjpg`, 640 px MJPEG at about 10 fps each. A camera opens only
  while someone watches or field mode reads it, and closes 20 s later.
- **CSI colour:** the IMX219 has no ISP tuning file, so the picture is magenta. The hub applies a grey-world white
  balance with smoothed, clamped gains.
- **Data collection:** `field.sh` checks for the hub on `127.0.0.1:5602`. If the hub is there, querra-scout reads
  full-size USB frames from it over the same QFC1 protocol as the simulator, with the gpsd fix in each frame header. If
  it is not, `field.sh` falls back to opening the camera and the GPS port itself. `patch_field_hub.py` is the change
  that was made to `field.sh` and `field-stop.sh`.
- **Radar:** the browser cannot read port 8077 directly because it sends no CORS headers. `/radar/events` relays the
  service's SSE stream, and the panel never opens the serial port. The sensor's RX wire is not connected, so firmware
  and mode show as "n/a (read-only)".
- **Vision demo** (`querra-vision`, a user unit with no `[Install]` section, so nothing starts it at boot) and the
  dual-camera recorder (`querra-field-recorder`, idle unless someone presses Record) take both cameras while they run.
  The panel then pauses its live view and says who has the cameras.

## Page

- **Data collection:** big Start and Stop, run name, elapsed time, frames, fps, run size, alerts, disk left, last
  detections. Stop runs `field-stop.sh` and the page says when it is safe to cut the power.
- **Settings:** start at boot (a user crontab line tagged `# querra-field`, off by default), the v0.2 or v0.3 engine
  (edits `field.sh` with a backup, only while collection is stopped), and the Vision demo on or off.
- **GPS:** fix type, satellites used and seen, HDOP, position with a map link, altitude, speed, heading, time since fix.
- **Radar:** a ±60°, 6 m fan with up to 3 targets and their trails, plus distance, angle and speed per target, and
  fps, frames, bad frames, error and the demo flag. It says "radar service offline" when the service is down.
- **System:** CPU and GPU temperature, power mode, RAM, uptime, free SSD and system disk, safe shutdown. Without
  passwordless poweroff, the page shows `sudo poweroff` instead.
- **Radar heatmap:** a decaying occupancy map over the fan, on a 10 cm grid. Each target adds a small gaussian and
  everything fades with a time constant of 20 s. It has on/off (remembered by the browser) and Clear buttons.
- **ROS 2:** Start and Stop for the `querra-ros` container (`/ssd/querra/ros2/ros.sh`), nodes and topic rates from
  the `querra_stats` node (`stats.json`), record a bag for 10, 30 or 60 s, the bag list with `.tar` downloads, the
  Foxglove address, and start at boot (user crontab `# querra-ros`, off by default). See [docs/ros2.md](../../docs/ros2.md).
- **Confirmed alerts** with map links, and **recent runs** with a streamed `.tar.gz` download.

## API

`GET /api/state`, `/api/gps`, `/api/radar`, `/radar/events`, `/stream/{usb,csi}.mjpg`, `/api/snap/{usb,csi}.jpg`,
`/api/runs`, `/api/alerts`, `/api/download/<run>.tar.gz`, `/api/ros/bags`, `/api/ros/bag/<bag>.tar`. `POST /api/field/start`, `/api/field/stop`,
`/api/autostart {on}`, `/api/ros/{start,stop}`, `/api/ros/record {secs}`, `/api/ros/autostart {on}`, `/api/model {version}`, `/api/vision {on}`, `/api/poweroff {confirm:"POWEROFF"}`.

The panel starts at boot from a user crontab line tagged `# querra-panel`. It never starts data collection by itself.

```bash
cd ~/querra-scout-20261107/panel && ./restart.sh     # (re)start the panel; data collection is not touched
```
