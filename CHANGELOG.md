# Changelog

## v0.4.0 · 2026-11-19 · ROS 2 phase 1 + radar heatmap

- `ros2/`: ROS 2 Humble in Docker on the SSD, with nodes for both cameras (from the panel hub), GPS (gpsd) and the
  LD2450 radar (ld2450-radar SSE), static TFs, foxglove_bridge on :8765 and MCAP recording to `/ssd/querra/bags`
- `querra_stats` node: topic rates and node list for the panel
- `ros2/ros.sh`: `start`, `stop`, `status`, `record N`, `bags`, `doctor`, `logs`, `shell` and `build`
- Panel: a ROS 2 card (start and stop, rates, record and download bags, Foxglove address, start at boot, off by
  default) and a decaying radar occupancy heatmap with on/off and Clear, in EN and PL
- Architecture diagram (mermaid) in the README and `docs/ros2.md`

## model-v0.3 · 2026-11-19 · fence detector

- `tools/make_dataset.py --style v2`: farms with many breaks and dead strands in random colours; `--split test`, `--mission-world`
- Held-out test set from new farm seeds; v0.3 test mAP50 0.912 (v0.2: 0.897), `wire_break` 0.684 (v0.2: 0.577)
- `tools/confirm.py`: an alert needs 5 of the last 8 frames to agree within 5 m on the ground; false alerts in the
  simulated mission 33 → 6, all three faults still found
- `tools/cam_record.py` and `tools/eval_mission.py`: record a mission and evaluate models offline

## model-v0.2 · 2026-11-19 · fence detector

- `tools/cam_stream.py`: streams the drone camera to the Jetson (TCP, JPEG and JSON telemetry per frame)
- `tools/make_dataset.py`: auto-labelled YOLO dataset from Gazebo ground truth (random farms, 7 classes)
- `tools/train_yolo.py`: YOLO11n training and ONNX export (416×640) for TensorRT
- Model v0.1 (epoch-2 checkpoint, val mAP50 0.72) and v0.2 (25 epochs, val mAP50 0.921) as GitHub releases
- Jetson end to end: 13.3 fps, all three faults found in the simulated mission. Known issue: false `wire_break`
  on dead (grey) wire, fix planned for v0.3. See `docs/retraining-log.md`.

## v0.2.0 · 2026-11-19

### LD2450 radar on the Jetson (first real sensor)
- `radar/server.py`: reads a HiLink LD2450 (24 GHz mmWave, up to 3 targets) through a CH340 USB-serial adapter
  at 256000 baud, decodes the 30-byte frames (about 11 per second), and survives the adapter being unplugged and replugged
- `radar/index.html`: live radar page
  - a ±60° fan with smooth target motion, trails, a heatmap and a 3 / 6 / 8 m range;
  - target cards with distance, angle, offsets, speed, motion, tracked time and closest point;
  - a 60-second distance chart and an activity feed.
- Streams to the browser with Server-Sent Events; `/state` gives the latest frame as JSON
- Reads the firmware version and switches single/multi-target mode when the sensor's RX is wired; read-only otherwise
- `ld2450-radar` Debian package (`radar/build_deb.sh`):
  - a systemd service that starts at boot;
  - an app icon and launcher that open a maximised app window;
  - settings in `/etc/default/ld2450-radar`.
- `--demo` mode with synthetic targets, for working without the sensor

### Ground station + drone (`./start.sh guard`)
- Ground station on a pole at the gate: RGB and thermal cameras on the mast, iToF depth sensor on the gate post
- Animals carry body heat for the thermal camera (16-bit, kelvin × 100, mapped to −5…45 °C in the stream)
- Simulated cameras published as RTSP through a local MediaMTX relay (`--share` for the local network), ready for a Jetson
- `ground/node.py`: sees animals outside the fence, counts animals through the gate, reads the fence monitor,
  and sends the drone; the mission report shows what triggered the flight
- Scenario: gate left open, a cow walks out; fault onset times (`onset_s`) drop the fence voltage mid-run
- Escaped animals near the gate are reported as "near the gate" instead of the nearest fault
- `stop.sh` also stops leftover guard loops, the RTSP relay and the stream bridge

### Jetson brain
- `sim/state_server.py`: read-only JSON state of the ground station, the drone and the latest events (port 8095)
- `brain/server.py` + `brain/index.html`: chat page on the Jetson; answers typed questions out loud from the RTSP frames
  and live facts with a local vision model (Ollama), facts-only fallback, Piper voice (or `say` / the browser)
- `docs/jetson-brain.md`: Jetson setup, direct-cable network, sharing sound in Zoom/Teams/Meet, scenario timeline
- Replay for demos:
  - `tools/record_scenario.py` records the three streams and the state timeline of a guard run;
  - `brain/server.py --replay` analyses the recording live on the Jetson, with a **Restart scenario** button.

### Reliability
- `start.sh` restarts PX4 when it hangs at startup (rare in SITL); stale state files are cleared before each run
- The state API drops ground-station data older than 5 s, so a stopped run never looks live

## v0.1.0 · 2026-11-14

First release: a complete electric-fence inspection flight in simulation.

### Simulation
- Pasture world generated from `fence.json`: 414 m two-strand electric fence on 75 posts, insulated gate,
  energizer, barn, trees, landing pad
- Three fault types: broken top wire (dangling ends), fallen post with wires on the ground, branch across the wires
- Herd of 14 cows and 10 sheep that graze and wander; three of them escaped near the faults
- Holybro X500 from PX4 with a lighter inspection camera (640×400, 15 fps, tilted 55° down)

### Mission
- Fence-following route 2.5 m outside the wire, rounded corners, 56 waypoints at 12 m and 5 m/s
- PX4 tuned for smooth flight (acceleration, jerk, yaw rate, RTL altitudes); arms in about 2 s by announcing itself as a GCS
- Simulated camera detector for faults and animals outside the fence polygon, with GPS for each finding
- Simulated EM voltage profile along both wires, showing where the top wire goes dead
- Report as JSON and HTML: map, faults with priority, escaped animals, voltage chart

### Languages
- Terminal output and the HTML report in English or Romanian (`--lang ro` or `GARDIAN_LANG=ro`)
- The report has an EN | RO switch; logs and JSON data always stay in English

### Tooling
- `start.sh` modes: automatic flight, manual PX4 console, headless, mission only, filmed demo
- `stop.sh` cleans up every process; `tools/install_launcher.sh` adds a Desktop double-click launcher
- `start.sh demo` records the README media: Gazebo stills, takeoff GIF, annotated inspection-camera frames, report screenshot
