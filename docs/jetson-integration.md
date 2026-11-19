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
