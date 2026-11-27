# Ground robot (UGV) · phase 0: simulation

The drone inspects open pasture. Under trees it can neither see the fence nor fly safely, and GNSS gets poor. A small
ground robot can patrol there: a fenced woodland paddock, a deer park, a zoo or safari enclosure. This is the
simulation phase: the robot, the forest and the patrol run before any hardware is bought.

Under a canopy, LiDAR and SLAM earn their place. Tree trunks are good landmarks, and GNSS cannot be trusted. On open
pasture the reverse holds, which is why the drone does without them.

```mermaid
flowchart LR
  subgraph MAC["Mac: the robot's body"]
    GEN["sim/gen_forest.py<br/>forest.json"]
    GZ["Gazebo Harmonic<br/>worlds/forest.sdf + querra_ugv"]
    REL["tools/ugv_relay.py :5611<br/>GNSS under canopy · odometry errors"]
  end
  subgraph JET["Jetson: the robot's brain (ROS 2 Humble, Docker)"]
    BR["ugv_bridge<br/>/ugv/* topics, TF"]
    PAT["ugv_patrol<br/>pure pursuit · LiDAR stop"]
    FOX["foxglove_bridge :8765"]
  end
  GEN --> GZ
  GZ -- "LiDAR 16×900 · camera · IMU · odometry · truth" --> REL
  REL -- "TCP, QUG1 frames" --> BR
  BR --> PAT
  PAT -- "/ugv/cmd_vel" --> BR
  BR -- "cmd_vel" --> REL --> GZ
  BR --> FOX
```

## The world

`forest.json` describes it; `sim/gen_forest.py` turns it into `worlds/forest.sdf`, the robot model and
`worlds/forest_meta.json` (route, spawn pose, sensor mounts, tree crowns, faults). Nothing generated is in git.

- **Enclosure:** an 8-sided paddock, 499 m of two-strand electric fence on 129 posts, 4 m apart. It reuses the
  pasture's fence and fault code (`sim/geo.py`, `sim/gen_world.py`), so a fault looks the same to both robots.
- **Faults:**
  - F1, wire_break (upper strand);
  - F2, branch_short (a branch across the wires);
  - F3, post_down;
  - F4, wire_break (lower strand);
  - F5, branch_short.
- **Forest:** 883 trees (a third spruce) in a 24 m band around the fence, with undergrowth.
  - **Route strip:** a cleared strip 1.3 m each side of the route, outside the fence.
  - **Obstacles next to the route:** 6 pinch points (a trunk 1.25–1.4 m from the route), 5 logs and 8 rocks. All
    of them have collisions.
  - **Clearing:** one fence edge runs through a clearing, with open sky.
  - **Sky cover along the route:** open for 10% of it, partial for 29%, dense canopy for 61%.
- **Route:** the fence polygon pushed 1.9 m outward, 516 m, a point every 0.5 m. The robot drives it once
  counter-clockwise, with the fence on its left: teach and repeat.

## The robot

| | |
|---|---|
| Base | 4×4 skid steer, 0.80 × 0.50 m, 30 kg, wheels r = 0.16 m. Tyre friction 1.0 along, 0.35 sideways, calibrated with `tools/ugv_calibrate.py` (commanded and real turns agree within 1%) |
| LiDAR | 16 beams, ±15°, 900 samples per turn, 0.3–40 m, 10 Hz, 0.8 m above the ground |
| Camera | 640×400, 100° wide, 10 fps, looking left at the fence, 6° down, 0.7 m up |
| IMU | 100 Hz (50 Hz to the Jetson) |
| Wheel odometry | Gazebo's, plus an error model: 1% distance scale, 2% turn scale, 1° heading drift per 100 m, only while moving |
| GNSS | 5 Hz. The truth plus noise (1 m under open sky, up to 4 m under canopy) and a wandering multipath bias (up to 6 m, 30 s correlation). Only a 2D fix above 60% sky cover; no fix above 90%. Sky cover is the share of the sky above a 15° mask that the crowns within 20 m hide, each weighted by 0.45 because leaves attenuate the signal rather than stop it. The robot is never told its true error |

## Run it

```bash
./ugv.sh                     # Mac: forest world, Gazebo window, relay on tcp://<mac>:5611 (headless: ./ugv.sh headless)
cd /ssd/querra/ros2 && ./ros.sh ugv tcp://<mac-ip>:5611            # Jetson: patrol on wheel odometry
./ros.sh ugv tcp://<mac-ip>:5611 pose:=truth                       # patrol on ground truth (tests the chain)
./ros.sh ugv tcp://<mac-ip>:5611 pose:=truth slam:=mapping         # teach: map while driving, saved to /ws/maps/forest
./ros.sh ugv tcp://<mac-ip>:5611 pose:=slam slam:=localization     # repeat: patrol on the SLAM pose against that map
./ros.sh ugv tcp://<mac-ip>:5611 pose:=slam slam:=localization detect:=true   # ... and look for faults on the way
python3 tools/ugv_eval.py --json                                   # Mac: score the patrols in the newest log
tools/ugv_series.sh 10 mmx@<jetson-ip> detect:=true                # Mac: ten patrols from clean starts, each scored
```

- **Fault alerts** (`detect:=true`): the ground-view detector ground-v0.1 runs on the side camera (TensorRT on the
  Jetson's GPU) and `ugv_alerts` confirms a fault when 5 of 8 frames taken 0.5 m of travel apart see it at the same
  spot on the fence (fallen posts from conf 0.5, the others from 0.7). Alerts go to `/fence/alerts` and
  `/ugv/alerts/markers` (yellow in the 3D view) and to the relay's log, where `tools/ugv_eval.py` scores them.

- **Foxglove:** connect to `ws://<jetson>:8765`, or `ws://localhost:8765` through an SSH tunnel for the web app, and
  import `ros2/foxglove/ugv-layout.json`. The layout shows the 3D view (point cloud, route, fence, faults, true
  path in green, odometry path in orange), the camera, a map with the GNSS fix, and a plot of odometry drift and
  GNSS error.
- **Restart a patrol from the spawn pose:** publish `restart` on `/ugv/patrol/cmd`.

## Results (2026-11-22)

**The chain.** Every stream arrives on the Jetson at its rate:

| Stream | Rate on the Jetson |
|---|---|
| LiDAR point cloud | 10 Hz, about 12,500 points |
| Camera | 10 fps, about 20 KB per JPEG |
| IMU | 50 Hz |
| Odometry | 28 Hz |
| GNSS | 5 Hz |

The patrol commands come back at 20 Hz. Gazebo runs at about 0.9× real time on the M2 with 878 trees, the LiDAR and
the camera.

**Patrols** (`tools/ugv_eval.py`, scored against the simulator's truth):

| Pose the patrol drives on | Result | Route | Off the route (max) | Odometry drift | Faults through the camera's view |
|---|---|---|---|---|---|
| Ground truth (control), first version of the world (sparser forest) | done | 99.8% in 706 s | 0.32 m | (not used) | 5 of 5 |
| Ground truth (control), final world, before turning on the spot | blocked at 221 m: a pinch-point trunk on the outside of a sharp corner (56°), after overshooting the corner by 0.5 m | 43% | 0.50 m | (not used) | 2 of 5 |
| Ground truth (control), final world, turning on the spot at sharp corners | done, no obstacle stops | 99.8% in 762 s (0.68 m/s) | 0.31 m | 5.3 m over the loop if it had driven on it (1.0 m per 100 m) | 5 of 5 |
| Wheel odometry, run 1 | blocked at 107 m: a spruce's low branches hung into the strip at 0.9–1.0 m | 21% | 0.81 m | 1.1 m (1.0 m per 100 m) | 1 of 5 |
| Wheel odometry, run 2 (spruces trimmed) | blocked at 95 m: a trunk at a pinch point, after drifting 0.6 m off the line | 19% | 0.61 m | 1.0 m (1.1 m per 100 m) | 1 of 5 |

After the blocked corner, `ugv_patrol` turns on the spot when the target is more than 35° off its heading, as skid
steers do. With that change, the control patrol completes the final world: the world is passable for a robot that
knows where it is.

**GNSS under the canopy.** Over the whole loop (the control patrol), the fix was there all the time, but 3D for
only 35% of it. The error was 4.4 m median and 9.9 m at the 95th percentile:

| Sky | Share of the loop | Error, median | Error, 95th percentile |
|---|---|---|---|
| Open (the clearing) | 10% | 1.9 m | 4.3 m |
| Partial cover | 25% | 4.5 m | 9.5 m |
| Dense canopy | 66% | 4.9 m | 10.4 m |

**What it means.** At its tightest, the strip leaves 0.59 m from the route centre to the nearest obstacle in the
robot's height band (`tools/ugv_clearance.py`; 5th percentile 1.1 m). The robot is 0.72 m wide, so it has about
0.2 m to spare there. A robot that holds its line and turns on the spot at sharp corners passes, as the control patrol shows. Wheel odometry is good to
about 1% of the distance, a good figure for a skid steer, and it still puts the robot 0.6 m off within 100 m. GNSS
error under the trees is many times the margin. The robot needs localisation from the trees themselves: LiDAR SLAM,
fused with odometry, the IMU and GNSS where the sky is open.

**A requirement found on the way.** Untrimmed spruces hang branches at 0.9–1.0 m, inside the robot's 1.0 m height
envelope. A strip a ground robot patrols needs its low branches cut back above about 1.3 m. That is a maintenance
requirement for the customer, not something the robot can solve.

## SLAM: teach and repeat

A ground robot that patrols the same strip every day does not need to discover the forest each time. It drives the
route once while a map is built (teach), then localises against that map on every patrol (repeat). Its error then
stays bounded by how well the scans match the map, instead of growing with the distance driven.

```mermaid
flowchart LR
  PC["/ugv/lidar/points<br/>3D, 16 beams"] --> P2L["pointcloud_to_laserscan<br/>0.33–1.7 m above ground"]
  P2L --> SCAN["/ugv/scan<br/>trunks · posts · bushes"]
  ODO["wheel odometry TF<br/>ugv_odom → ugv_base_link"] --> SLAM
  SCAN --> SLAM["slam_toolbox<br/>mapping · localization"]
  SLAM -- "TF ugv_slam_map → ugv_odom" --> BR["ugv_bridge<br/>/ugv/slam_pose"]
  BR --> PAT["ugv_patrol<br/>pose:=slam"]
  SLAM -- "patrol done" --> MAP["/ws/maps/forest<br/>.posegraph · .data"]
```

- **Scan:** `pointcloud_to_laserscan` turns the 3D point cloud into a 2D scan from a slice 0.33–1.7 m above the
  ground. That holds the trunks, fence posts and bushes, and leaves out the ground and the crowns.
- **SLAM:** slam_toolbox (`ros2/src/querra_fence_ros/config/ugv_slam_*.yaml`) uses the wheel odometry as its prior.
  Its map frame starts at the spawn pose; `ugv_bridge` places it in the world.
- **Why not KISS-ICP:** KISS-ICP (3D LiDAR odometry) has no Humble package for arm64. slam_toolbox does, and it
  also does what LiDAR odometry alone cannot: close the loop, and localise against a saved map.
- **Teach:** the mapping run drives on ground truth, standing in for an operator who drives the robot by remote
  control once. When the patrol is done, `ugv_patrol` asks slam_toolbox to save the map.
- **Repeat:** `slam:=localization pose:=slam`. The patrol drives on the SLAM pose, localised against that map.

**What the LiDAR sees.** These are 209 scans from 33 m of a repeat patrol through the densest part of the forest,
each placed with the simulator's true pose. Orange is the band 0.33–1.68 m above the ground, the slice that becomes
the 2D scan SLAM matches against its map. It cuts every trunk, every fence post and the wires, and leaves out the
ground and the crowns, which move with the wind and the seasons on a real site.

![The forest strip in the ground robot's LiDAR, seen from ahead of the robot: tree trunks banded orange where they cross the SLAM slice, the fence wire as an orange line, crowns overhead, the path driven in white](media/ugv-lidar-forest.jpg)

![The same cloud from above and to the side: trunks as columns with the SLAM slice in orange, the fence posts and wires, the path ending at the robot](media/ugv-lidar-above.jpg)

`tools/ugv_lidar_view.sh [SECONDS]` makes both from the running simulation. It only listens to Gazebo, so it does not
disturb a patrol.

**The whole loop, one scan, and the faults.** With no patrol and no Jetson, `tools/ugv_lidar_view.sh --sweep` places
the robot every 1.5 m along the route (every 0.3 m within 8 m of a fault) and keeps one scan at each of 571 stops.

![The whole forest loop in LiDAR, from high above its south side: trees as columns with crowns, the robot's route in white, the five faults marked](media/ugv-lidar-loop.jpg)

A single scan is sparse: about 13,000 points in 16 rings, a handful on each trunk. SLAM's accuracy comes from matching
each such scan against the map built on the teach run, not from any one scan.

![One LiDAR scan as the sensor delivers it in 0.1 s: 16 rings on the ground and a few points on each trunk around the robot](media/ugv-lidar-single.jpg)

The faults show in 3D too: a branch lying across the wires (F2), and the wires running down to the ground where a post
fell (F3). The simulated wires are 36 mm thick, like wide polytape. A real 2.5 mm steel wire would barely show in a
16-beam LiDAR, so the camera stays the main fault sensor.

<p>
  <img src="media/ugv-lidar-F2.jpg" width="49%" alt="F2 in LiDAR: a branch lying across the fence wires, between two posts">
  <img src="media/ugv-lidar-F3.jpg" width="49%" alt="F3 in LiDAR: the fence wires run down to the ground where a post fell">
</p>

**The map it localises against.** This is slam_toolbox's occupancy grid from the teach run, as the Jetson holds it
during a repeat patrol, placed in the world through the spawn pose, with the true trunk positions on top. The trunks
the LiDAR saw sit in their rings, around the whole loop: from each true trunk centre to the nearest occupied cell is
0.10 m on median and 0.32 m at the 95th percentile over 739 trunks, about a trunk's radius (0.14–0.32 m). The map from
teach 3 (in the table below) measured 0.56 and 1.57 m, about a metre off at the far side of the loop: the warp that
repeat 1 ran into.

![The SLAM map against the true forest: occupied cells in black, true trunk positions as orange rings, the taught route in blue; close-ups at the start and at the far side of the loop show the trunks inside their rings and the fence line through the true posts](media/ugv-slam-map.png)

`tools/ugv_slam_map.sh` makes it while SLAM runs (`./ros.sh ugv … slam:=localization pose:=slam patrol:=false` is
enough): `ros2/grab_map.py` saves `/map` on the Jetson, and `tools/ugv_slam_map.py` draws it and measures the fit.

**Results so far (2026-11-22):**

| Run | SLAM error (median / max / at the end) | Wheel odometry drift | Notes |
|---|---|---|---|
| Teach 1: stamps on arrival, default settings | 3.1 / 7.1 / 6.4 m | 4.6 m | Worse than odometry. The heading drifted on every left turn, because each stream's own delay was mixed into its stamps |
| Teach 2: Gazebo's simulation time on every sample (`/clock`), defaults | 3.7 / 9.0 / 8.3 m | 6.9 m | Still no loop closure. The indoor defaults trust the odometry's heading over the scans and search only 4 m for a loop |
| Teach 3: simulation time + outdoor tuning | 1.08 / 4.6 m, **0.01 m after the loop closed** | 14.8 m | The loop closed at the start. The map was saved after the closure |
| Repeat 1: localisation against that map, patrol on the SLAM pose | 0.84 / 6.3 m over the first 275 m | 7 m | Passed the tight spots at 95 m and 107 m where odometry stopped. For 400 s localisation held steady: 1.1–1.3 m from the truth, heading within 0.3°. Then the Wi-Fi link between the Mac and the Jetson stalled (4–5 s gaps from 414 s); localisation lost its heading in the last 10 s, and the link carried nothing for about 13 minutes. The patrol held still on its stale pose, as it should |
| Teach 4: 5 GHz link; the route saved as the map sees it | 1.01 / 2.41 m, 0.38 m at the end | 4.5 m | No link gaps. The saved route (the pose graph after the loop closed, 1,536 points) lies 0.13 m from the true route on median, 0.39 m at most |
| Repeat 3: as repeat 2, with the localisation and bridge lighter on the CPU (below); Wi-Fi power saving off | 0.26 / 0.83 m, 0.05 m at the end | 4.3 m | The whole loop: 99.7% in 832 s (0.62 m/s), no obstacle stops, 5 of 5 faults through the camera's view. Off the true route: 0.01 m median, 0.18 m p95, 0.62 m max. No link gaps |
| **Repeat 2: localisation, patrol on the SLAM pose along the taught route** | 0.30 / 1.13 m, 0.02 m at the end | 4.2 m | **The whole loop: 99.7% in 735 s (0.70 m/s), no obstacle stops, 5 of 5 faults through the camera's view. Off the true route: 0.01 m median, 0.17 m p95, 0.60 m max.** One 3.3 s link gap, ridden out |
| **Series: 8 repeat patrols in a row, each from a clean start** (`tools/ugv_series.sh 8`, as repeat 3) | 0.25–0.27 m median, 0.42–0.44 m p95, 0.82–0.98 m max per patrol | 1.8–4.3 m | **8 of 8 completed the loop:** 99.7–99.8% in 717–751 s, 0.18–0.19 m p95 off the true route (0.59–0.61 m max), no obstacle stops, no link gaps, 5 of 5 faults through the camera's view in every patrol |

**Repeat 3 from above.** Black is where the robot really drove, blue is where SLAM on the Jetson placed it, and
orange is where wheel odometry alone would have placed it. Blue covers black the whole way round; orange drifts up to
4.6 m off. Close-up 1 is the moment SLAM was furthest off, at the corner by F2: 0.83 m along the path and 0.03 m
sideways, so it did not push the robot off the route. Close-up 2 is the end of the loop, back at the start.

![Repeat 3 from above: the true path and the SLAM position overlap the whole way round, while wheel odometry drifts up to 4.6 m off; close-ups of the worst SLAM moment and of the end of the loop](media/ugv-patrol-top.svg)

The same patrol as error against the distance driven. Wheel odometry's error grows with the distance. GNSS under the
crowns swings between 1.5 and 9 m, which is why the patrol does not steer on it. SLAM stays under a metre.

![Position error along repeat 3: SLAM stays under 1 m (median 0.26 m), wheel odometry grows to 4.3 m, GNSS under the trees swings between 1.5 and 9 m (median 4.3 m)](media/ugv-error.svg)

Both figures come from the patrol's log: `python3 tools/ugv_figures.py run/ugv/<time>` (after `tools/ugv_eval.py
--json`, whose numbers they reuse).

**On the Orin Nano** during repeat 2 (before the CPU cut below): the localisation node used about two CPU cores,
`ugv_bridge` 60–75% of one, the stats node about a third of one.

**Why the Jetson stopped answering.** It did not crash or reboot: its log runs on without a gap, with no memory,
thermal or network event, and the ROS container stayed up. Its link is 2.4 GHz Wi-Fi at about −59 dBm, which carries
the robot's stream (LiDAR, camera, IMU, odometry: about 0.5 MB/s) plus Foxglove. That link stalled and then dropped.
On a real robot the sensors are wired to the Jetson; the Wi-Fi link exists only because the Mac plays the robot's
body. For simulation runs the Jetson should be on Ethernet (or 5 GHz).

**The steady 1.1–1.3 m error is the map's warp.** The teach run's drift was closed at the loop's end, which spreads
the correction along the loop but leaves the map up to about a metre off the world. The route comes from the world
(`forest_meta.json`), so a robot localised in the map follows it up to a metre off. Real teach and repeat records the
route in the map's own frame during the teach run, so the warp does not matter.

**Teach and repeat fixes it.** With the route saved as the map sees it (`ugv_patrol` saves slam_toolbox's pose graph
after the loop closes, in `/ws/maps/forest.route.json`), the route and the SLAM pose come from the same map. In
repeat 2 the SLAM pose was 0.30 m from the truth on median, yet the robot drove 0.01 m from the true route on median
and 0.17 m at the 95th percentile: the map's warp cancels out.

**CPU on the Orin Nano** (`./ros.sh cpu 120`, two minutes into a repeat patrol, % of one core; the board has six):

| Process | Before | After | What changed |
|---|---|---|---|
| slam_toolbox localisation | 194% | **39%** | The localisation config only (the mapping one is unchanged): a scan every 0.5 m instead of 0.3 m, a shorter local chain, a smaller per-step window, 2° coarse angles, an 8 m window to match back to the map |
| `ugv_bridge` | 77% | **33%** | The point cloud and JPEGs go to ROS as `array('B')`. rclpy checks a `bytes` value one element at a time in Python, which for the cloud is 230 KB ten times a second. The visualisation trails are published every 2 s, capped at 2,000 points |
| stats | 39% | 28% | The ground robot's launch skips `/clock`, `/tf`, `/map` (14 MB), the eval and trail topics |
| `ugv_patrol` | 12% | 12% | |
| pointcloud_to_laserscan | 5% | 6% | |
| **All, in the container** | **327%** | **119%** | the board 57% → 22% busy overall |

Accuracy did not suffer: repeat 3 (after) against repeat 2 (before): 0.18 against 0.17 m p95 off the route, SLAM error
0.26 against 0.30 m median, and its maximum went from 1.13 to 0.83 m. The robot drove a little slower (0.62 against
0.70 m/s).

Open: the stats node (28%) and the patrol's point-cloud check, if the CPU is needed for the detector.

## Phase 0 goals

| Goal | Status |
|---|---|
| The whole chain runs (Gazebo → relay → ROS 2 on the Jetson → commands back), every sensor at its rate | done |
| The robot completes the loop autonomously in at least 9 of 10 patrols | **yes on SLAM (teach and repeat): 10 of 10.** Repeats 2 and 3, then 8 of 8 in a row from clean starts (2026-11-22). On wheel odometry: no, blocked at about 100 m in 2 of 2 patrols. On ground truth: yes |
| At least 4 of 5 faults found, at most 1 false alert per patrol | not yet. All 5 pass through the camera's view, but model-v0.5 knows only the drone's 55° view; the ground view needs its own data and model |
| Localisation error under 1 m with poor GNSS, on the Orin Nano | yes: in the 9 patrols since the CPU cut, 0.25–0.27 m median, 0.42–0.44 m p95, and under 1 m at every moment (worst 0.98 m), with the whole ground-robot stack at 119% of one core of six (localisation 39%). Repeat 2, before the cut, peaked at 1.13 m. GNSS under the canopy: 4.3 m median |

## Next steps

1. **Localisation robustness.** Teach and repeat on slam_toolbox meets the goals in simulation (10 of 10 loops,
   under 1 m). Next, test it against a forest that changed after the teach run (trees and bushes added or removed),
   and fuse the IMU and GNSS in an EKF (`robot_localization`) so the pose holds when scan matching weakens. The
   patrol takes its pose from a topic, so it switches without code changes.
2. **Ground-view detector.** The first one, ground-v0.1 ([run record](../ml/runs/ground-v0.1)), was trained on
   frames rendered from the robot's camera pose in random forests. Live on the Jetson (`detect:=true`): 10 of 10
   patrols, **50 of 50 faults found, 0 false alerts**, each alert 0.4–1.4 m from its fault. The fallen post is the
   thin margin (6–7 steps show it where 5 are needed). ground-v0.2 ([run record](../ml/runs/ground-v0.2)), with
   more fallen-post data, finds every fault with every class from conf 0.7 offline (29 of 29 on four patrols); it
   is a candidate until its live patrols. ground-v0.3 ([run record](../ml/runs/ground-v0.3)) also learned real
   conductors (steel wire, polywire, rope, tape) and finds thin wire almost as well as thick conductors, again 29
   of 29 offline; with it, broken wires should count from conf 0.6.
3. **Ten patrols per change** with `tools/ugv_series.sh 10` (each from a clean start, scored with
   `tools/ugv_eval.py`), as with the drone's models.
4. **The real walk.** Walk a real forest fence with the Jetson, the camera at 0.7 m and the u-blox logging its
   accuracy. That calibrates the GNSS and odometry models. The first real ground-view images can come before it,
   from a phone held where the camera would be ([phone-walk.md](phone-walk.md)), labelled with
   [labelling.md](labelling.md).

## Known limits

- **Flat ground.** No slopes, mud or roots yet: the terrain is the main risk for a real robot.
- **Near-field blind zone.** The LiDAR's lowest beam reaches the ground about 3 m ahead. A low log or rock closer
  than about 2 m is invisible to it. A real robot adds a tilted LiDAR or a depth camera.
- **No obstacle avoidance.** The patrol stops for an obstacle in its path and gives up after 20 s.
- **Synthetic error models.** The odometry and GNSS errors are models, not measurements. The planned walk along a
  real forest fence, with the u-blox logging its accuracy, is what calibrates them.
- **Detector.** The fence detector (model-v0.5) has only seen the fence from above. The ground view needs its own
  data and model.
