# Changelog

## v0.8.0 · 2026-11-20 · re-fly the confirmed faults; nine languages

- **`fence_refly` node (phase 3, part 2, `refly:=true`).** After the inspection mission, when PX4 enters Return, the
  Jetson takes over in OFFBOARD over uXRCE-DDS.
  - It visits every confirmed alert nearest-first at 6 m, stopping 4.2 m before the fault so the 55° camera centres
    it.
  - It hovers 5 s, counts the detector frames, then hands back with Return.
  - The setpoint moves at most 4 m/s.
  - The offboard stream stays alive until PX4 is in Return.
  - If a pilot or a failsafe changes the mode, the node aborts.
- **Tested in SITL (5 min 13 s, 852 m).** The handover, the 8 visits, the Return and the landing all worked.
  - The close-up verdicts were not reliable: the model was trained at 12 m.
  - The verdict is now a majority rule (at least half of the hover frames), chosen after this one flight and not
    validated. Numbers in `docs/ros2.md`.
- **Nine languages** (EN, RO, PL, PT, DE, ES, HR, BG, DA):
  - **Simulation and report:** `sim/i18n.py` covers the terminal and the HTML report, which has a language menu.
    `--lang <code>` picks the language. JSON text fields hold every language, and older EN/RO reports still open.
  - **READMEs:** `README.<lang>.md` for every language. The translated prose lives in `docs/i18n/*.tpl.md`, and
    `docs/i18n/build_readmes.py` copies the shared parts (diagrams, commands, config) from `README.md`.
  - **Project page:** a language menu, with the translations in `docs/assets/i18n/<lang>.json`, loaded on demand.

## v0.7.0 · 2026-11-20 · ROS 2 phase 3, part 1: PX4 over uXRCE-DDS

- **micro-ROS agent** in the ROS 2 image: a Micro-XRCE-DDS agent built against Humble's Fast DDS. `px4:=true` starts
  it on UDP 8888, and `./ros.sh doctor` checks it.
- **`px4_msgs`** (minimal): eight messages copied unchanged from the PX4 tree the simulation runs (v1.18 beta). They
  cover the pose, the status and the offboard messages for the next step.
- **`px4_pose` node**: PX4's global position, local position and status become two topics:
  - `/px4/telemetry` (position, altitude, heading, speed, flight phase);
  - `/px4/gps/fix`.
  With `px4:=true`, `alert_confirm` places alerts with this pose.
- **`tools/uxrce_relay.py`** forwards PX4 SITL's client from the Mac to the Jetson. `start.sh` exports
  `ROS_DOMAIN_ID=42`. PX4 itself is unchanged.
- **`./ros.sh demo tcp://MAC:5601 px4:=true`** passes extra launch arguments, and the PX4 topics are recorded in bags.
- **Tested in one full simulated flight**:
  - the PX4 pose matched the simulator's telemetry within 0.62 m (median) and 2.2 m (max);
  - the three real faults were alerted 2.4 m, 3.0 m and 4.2 m from their true positions.
- **Docs and project page**: phase 3 part 1 is marked done. Next is re-flying a confirmed fault (offboard).

## v0.6.0 · 2026-11-20 · safe fence: new icon, project page, bug fixes

- **Project page** on GitHub Pages (`docs/index.html`): what works today, sensors in and alerts out (live, simulated,
  planned) and the roadmap.
  - It has an **EN | PL** switch, picks Polish for Polish browsers, and links work with `?lang=pl`.
- **README in Polish**: `README.pl.md`, linked from the top of `README.md`.
- **New icon**: a shield around a live electric fence. It is used in the dock (48–512 px) and as the panel's favicon
  and phone home-screen icon.
- **Launcher** (`querra-fence-panel_0.6.0_arm64.deb`, which upgrades and replaces 0.5.1):
  - new **Restart the panel** right-click action, plus `--restart` and `--version`;
  - opens Chromium with `--disable-gpu` on the Jetson; the GPU initialisation failure left a blank window;
  - falls back to Firefox when Chromium fails, and logs browser output to `~/.cache/querra-fence.log`;
  - checks that the panel answers with the cheap `GET /`, and starts it through `restart.sh`;
  - `--ros-demo` sends the panel PIN when one is required;
  - `--foxglove` shows the LAN address;
  - upgrades no longer re-pin the dock icon;
  - `build.sh` creates the folders it needs, so the package builds from a clean clone.
- **Alerts**:
  - `/fence/alerts` carries one message per confirmed alert (transient-local), so a late Foxglove client or bag gets
    every alert;
  - re-sightings moved to `/fence/alerts/updates`;
  - the panel's "last alert" is the latest confirmed one.
- **ROS 2 nodes**:
  - `fence_detector` survives a failed frame instead of stopping inference silently;
  - `sim_camera` retries a missing or empty recording and survives a dropped live stream;
  - `querra_stats` no longer subscribes to `/detections/image`, so annotation runs only for real viewers.
- **`ros.sh`**:
  - asks Docker for the NVIDIA runtime;
  - mounts host folders only when they exist;
  - `demo` checks the recording before starting;
  - `doctor` checks the runtime, the v0.3 engine, the demo recording and `/ssd`, and no longer stops early when `df`
    fails.
- **Container rebuild:** the container rebuilds the workspace when the content of `src/` changes, not only its mtimes.
- **Panel:**
  - the radar shows "no data" when the sensor is connected but silent;
  - the ROS 2 card shows when its stats are stale;
  - MJPEG streams notice clients that left and never send an old frame as live;
  - the crontab is read at most every 5 s;
  - `restart.sh` waits for the old panel to exit and reports whether the new one answers.

## v0.5.1 · 2026-11-19 · desktop launcher

- `querra-fence-panel_0.5.1_arm64.deb`: **Querra Fence** in the GNOME dock; opens the panel in an app window and starts
  the panel first if it is not running; right-click actions for the ROS 2 demo and the Foxglove address
- `packaging/deb/` sources and `build.sh`

## v0.5.0 · 2026-11-19 · ROS 2 phase 2: detector + confirmation

- `fence_detector` node: YOLO11n model-v0.3 TensorRT FP16 on the Jetson GPU, `vision_msgs/Detection2DArray`, annotated
  image and latency topics; 15 Hz, about 26 ms per frame (JPEG decode + TensorRT + post-processing)
- `alert_confirm` node: 5 of 8 frames within 5 m at conf 0.7 (`tools/confirm.py`), `FenceAlert`, `NavSatFix` per alert
  and a count, all transient-local
- `sim_camera` node: the Gazebo camera and telemetry from the live simulation (QFC1) or a recorded mission, looped
- `querra_fence_msgs`: `Telemetry` and `FenceAlert`
- Launch argument `detector:=none|sim|usb`; `./ros.sh demo [tcp://mac:5601]`; TensorRT and CUDA mounted read-only from JetPack
- Panel: **Demo** button and detector frames, boxes, latency and confirmed alerts in the ROS 2 card (EN and PL)
- Foxglove layout `ros2/foxglove/querra-layout.json`, interview walkthrough `docs/interview-demo.md`
- New panel demo GIFs (desktop and phone) and screenshot, with GPS coordinates blurred

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
