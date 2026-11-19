# Jetson integration (querra-scout)

The detector runs inside **querra-scout**, the camera and GPS recorder on the Jetson
(`/home/mmx/querra-scout-20261107`). That code is **not** in this repository. This page describes what was added
there, so the two halves can be followed together.

## Simulation in the loop

```
Mac: Gazebo + PX4 ──/fence_cam/image──▶ tools/cam_stream.py ──TCP :5601, JPEG + JSON telemetry──▶ Jetson
```

- **`tools/cam_stream.py`** (this repo): subscribes to the drone camera in Gazebo and encodes each frame as JPEG
  (ffmpeg, about 1.6 ms). It sends `QFC1 | header length | JPEG length | JSON | JPEG`. The JSON header carries the sim
  time, the send time and the drone telemetry from `run/drone_state.json` (lat, lon, altitude, heading, flight phase).
  It never opens a MAVLink port, so it does not interfere with the mission.
- **querra-scout `sim:<host>:<port>` source** (`capture.py`): reads that stream like a camera. Its GPS comes from the
  telemetry (`SimTelemetryGPS` in `gps.py`), so `--require-gps` works without a GPS receiver. Measured 14.8 fps,
  Gazebo to Jetson in a few ms on Wi-Fi.

## Detector

- **`querra_scout/detector.py`**: `YOLODetector` loads the TensorRT engine through the CUDA runtime with `ctypes`
  (no extra Python packages). It letterboxes the frame to the engine input, runs FP16 inference, then applies
  class-aware NMS with OpenCV.
- **`runtime.py` / `cli.py`**: new options `--detector ENGINE`, `--det-conf`, `--annotate-interval`.
  - Every frame's boxes go to `detections.jsonl` (with GPS and altitude) and into the observation record.
  - Annotated JPEGs are saved to `annotated/`.

```bash
python3 -s jetson-launch.py run --source sim:Cosmins-MacBook-Air.local:5601 \
  --model models/wheat-v2.onnx --provider tensorrt-native --engine models/tensorrt-fp32/model.engine \
  --detector models/fence-yolo/fence-yolo11n-fp16.engine --duration 165 --rate 0 --no-save-images \
  --annotate-interval 2 --material synthetic --output runs/<name>
```

## Confirmed alerts

- **`querra_scout/confirm.py`**: the same file as `tools/confirm.py` in this repo.
- **Runtime options:** `--confirm-n 5 --confirm-m 8 --confirm-radius 5 --confirm-conf 0.7` (the defaults).
- **What happens per frame:** every fault box is placed on the ground (GPS, altitude, heading, 55° camera). A fault
  becomes an alert only when N of the last M frames agree within the radius.
- **Output:** each alert is printed as `ALERT ...` and appended to `alerts.jsonl`. `detections.jsonl` now records
  `heading_deg` too.
- **Without heading** (a real GPS with no compass) the alert falls back to the drone's own position.

## Field mode

- **`field.sh`**: runs the USB Arducam (1280×720 MJPG) with the u-blox 7 GPS and the fence detector (confidence 0.4).
  - Records in 10-minute chunks to the SSD (`/ssd/querra/field-runs/`), so a power cut loses little.
  - Saves a raw JPEG every second for retraining, plus an annotated frame every 5 s.
  - Stops when free space runs low. About 580 MB per hour.
- **`field-stop.sh`**: stops cleanly and runs `sync`.
- **Status:** `field-status.txt` is updated every 10 s with fps, GPS state, last detections and free disk.
- **Autostart** (crontab or systemd unit) is prepared in `deployment/` but **not enabled**.

The raw field frames are the next training data: real grass, real light and real wire, labelled and added on top of
the synthetic set.

## Field control panel

`http://mmx-desktop.local:8080` (or the Jetson's IP) is the field dashboard, in English or Polish. It shows both
cameras live, the LD2450 radar targets and the GPS fix, and starts and stops data collection. It also switches start at
boot, the Vision demo and the detector engine, lists runs with downloads and confirmed alerts with map links, and offers
a safe shutdown. The panel is the only owner of the cameras. Field mode reads the USB camera and the gpsd fix from it
over QFC1 on `127.0.0.1:5602`, so the live view keeps running while data is collected. The code and the device-ownership
table are in [`jetson/panel/`](../jetson/panel/).

