# Changelog

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
