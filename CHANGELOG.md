# Changelog

## Unreleased

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
