# Changelog

## Unreleased

- **model-v0.6, real fence conductors (not adopted)** ([ml/runs/model-v0.6](ml/runs/model-v0.6)): fine-tuned from
  model-v0.5 with 3,000 frames of 12 new farms at flight poses in steel wire, polywire, polyrope and polytape (steel
  wire and polywire without wire boxes, too thin to see from 11 m), on the M2's GPU in 1.5 h. Fallen posts on thin wire
  are found far more often (from conf 0.7: steel wire 75%, polywire 76%; model-v0.5 59%, 61%), but broken wires on
  real conductors still are not (rope 3%, tape 8%), and false broken wires rose: one false alert in the mission replay
  (model-v0.5: none), 15 false frames from 0.7 (1), 3.5% of TTPLA's real photos from 0.5 (0.4%). No threshold makes
  up for it. model-v0.5 stays the default; a new registry status, `not adopted`, keeps model-v0.6 for comparison.
- **Drafting real photos with models trained on real images** ([docs/labelling.md](docs/labelling.md)):
  `label_drafts.py draft --model` takes several models and merges their boxes. A YOLO-World model drafts from text
  prompts (posts, by default), a COCO model drafts the classes it shares (cow, sheep), and `MODEL.pt@classes` keeps a
  model to some classes. On the 176 Commons photos so far: 148 drafts (51 posts, 75 cows, 16 sheep, 6 faults) where
  ground-v0.3 alone gave 2,633, mostly noise. A COCO detector (`yolo11n.pt`) boxes no animal in any of TTPLA's 1,242
  photos (model-v0.5: a cow in 84%), so it is the better animal detector for now. `make_dataset.sh --no-wire-labels
  steel,polywire` leaves out the wire boxes of conductors too thin to see from the flight.

- **The first real images** ([ml/datasets.json](ml/datasets.json)): `tools/fetch_commons.py` collects openly licensed
  photos of electric fences from Wikimedia Commons with their author and licence (467 pass; drafted by ground-v0.3 for
  review with `tools/label_drafts.py`, whose `draft` now adds photos that join a folder later). `tools/ttpla_check.py`
  runs a drone model on TTPLA's 1,242 real drone photos of power lines ([ml/runs/model-v0.5](ml/runs/model-v0.5#real-photos-power-lines-ttpla)):
  model-v0.5 raises a fault in 2 of them from conf 0.7 (one a real tree on the lines), but boxes a cow in 25% (bushes,
  windows, walls) and barely sees the real cables and poles. On the first 50 fence photos ground-v0.3 boxes few posts
  and wires and no fault from 0.5. Real labelled images, not more simulation, are what the models need next.
- **A sharper camera for the ground robot, a test** ([ml/runs/ground-v0.3](ml/runs/ground-v0.3#a-sharper-camera)):
  `make_ground_dataset.sh --width` renders the robot's lens with more pixels. At 1,280 and 1,920 pixels a 2.5 mm wire
  is a crisp line, but ground-v0.3 cannot use it: shrunk to the 640 pixels it reads, the sharper frames score within
  a few points of the 640 camera, and at full size it fails on every look (mAP50 0.75 at 1,280, 0.18 at 1,920),
  because every object is 2–3 times larger than anything it learned. A sharper camera needs a model trained at its
  size.
- **The drone on real fence conductors, a stress test** ([ml/runs/model-v0.5](ml/runs/model-v0.5#fence-looks-a-stress-test)):
  `make_dataset.sh --fence-look` and `--supersample` for the drone's dataset tool (classic and rich worlds unchanged).
  On its flight test farms model-v0.5 finds no broken wire in any real conductor, at conf 0.7 or 0.5: from 11–12 m a
  2.5 mm wire is a tenth of a pixel, and on rope and tape, which it sees (`wire` mAP50 0.95, 0.97), it never learned
  what a real break looks like. No false alarms where the wire vanishes; fallen posts drop from 93% to about 60% on
  thin wire; posts and branches hold. Broken thin wire is the ground robot's job, or a low close pass (the DJI Mini 4
  Pro's 4K camera sees a 2.5 mm wire as one pixel from 5.5 m).
- **ground-v0.3, thin wire (candidate)** ([ml/runs/ground-v0.3](ml/runs/ground-v0.3)): fine-tuned from ground-v0.2
  with 4,000 frames of 16 new forests in real conductors (6 steel wire, 6 polywire, 2 rope, 2 tape; 3x supersampled),
  on the M2's GPU in 1.2 h. On the stress test's forests thin wire now scores almost like thick conductors: `wire`
  mAP50 0.95 on steel and polywire (ground-v0.2: 0.44, 0.20), broken wires found from conf 0.7 in 77% and 72% of the
  frames (17%, 1%), from 0.5 in 90%. Classic test mAP50 0.981 (0.979); 29 of 29 faults and no false alert on the four
  patrols. Less confident on broken wires (classic test from 0.7: 79%, ground-v0.2 85%; from 0.6: 90%), so with it
  broken wires should count from 0.6. Not yet live on the Jetson or tested on real footage.
- **Fence looks, a stress test** ([ml/runs/ground-v0.2](ml/runs/ground-v0.2)): every model so far learned strands drawn
  as 3.6 cm glowing yellow rods. `make_ground_dataset.sh --fence-look` draws real conductors at their real size
  (steel 2.5 mm, polywire 3 mm, polyrope 6 mm, polytape 40 mm; `sim/gen_world.py` FENCE_LOOKS, classic unchanged) and
  `--supersample 3` renders a wire thinner than a pixel as the faint line a camera records. On the same test forests
  ground-v0.2 holds on tape and rope (mAP50 0.98, 0.97) but not on thin wire: `wire` mAP50 0.44 (steel) and 0.20
  (polywire), broken wires found from conf 0.7 in 17% and 1% of the frames (classic: 86%). Part of it is the camera:
  640 pixels across 100 degrees puts a 2.5 mm wire 1.9 m away at half a pixel.
- **Training on the M2's GPU:** `--device mps --batch 8` is 4x faster than the CPU with the same first-epoch scores;
  batch 16 does not fit in 8 GB.
- **Phone alerts** ([docs/phone-alerts.md](docs/phone-alerts.md)): each new fence alert, from the drone or the ground
  robot, arrives on the phone through ntfy or Telegram with the camera frame that confirmed it (the fault boxed) and
  a map link. `tools/notify.py setup ntfy|telegram`, `status`, `test`; the settings live in
  `~/.config/querra/notify.json`, never in git, and `ros.sh` mounts them read-only into the container. The ROS 2
  node `phone_alerts` (`notify:=true` with `./ros.sh ugv … detect:=true` or `./ros.sh demo`) picks the alert's own
  frame by its time stamp, at no extra cost to the detector. 5 messages at once, then one every 5 minutes, with
  waiting alerts sent together as a summary; retries for about an hour without a network; tokens and topics never
  in the logs. `tools/video_eval.py --notify` sends a video's alerts. Tested against a local stand-in for both
  services (20 tests) and on the simulated walk: 8 alerts as 6 messages. Not yet on a real phone or the Jetson.
- **Tests and checks on every push** ([tests/](tests)): 64 tests with pytest, about 15 s on the Mac, no GPU, Gazebo or
  ROS 2 needed (ROS 2 stand-ins in `tests/conftest.py`). They cover the drone's and the ground robot's alert
  confirmation (and that the Jetson's `confirm.py` keeps the same logic as `tools/confirm.py`), DJI subtitles,
  patrol scoring end to end, the labelling server, the cooling breaks and the model registry. Each was checked
  against a real bug of this project put back in. `.github/workflows/checks.yml` runs them on GitHub with the
  registry, release-notes and translated-README checks. `tools/train_with_breaks.py` takes its waits from the
  environment (`BREAKS_POLL_S`, `BREAKS_SETTLE_S`, `BREAKS_STOP_WAIT_S`) so the tests can shorten them.

## v0.14.0 · 2026-11-26 · ready for real footage: a phone walk, a labelling page, and ground-v0.2 (candidate)

- **Labelling real footage** ([docs/labelling.md](docs/labelling.md)): `tools/label_drafts.py draft` takes frames
  from a video (or a folder of photos) and lets a model draft the boxes; `serve` opens a review page on 127.0.0.1
  (`tools/label_ui.html`: draw, move, resize, class keys, undo, zoom; each frame saved on Enter, skipped frames left
  out); `score` scores any model on the reviewed frames: mAP50 per class and, per fault class, recall, precision and
  frames with a false box at conf 0.5 and 0.7. No internet and no extra packages for the page; the server answers
  only its own page (Host check, JSON-only saves). Tested on a simulated walk, and the page driven in headless
  Chrome.
- **The phone walk** ([docs/phone-walk.md](docs/phone-walk.md)): how to film a real fence the way the ground robot's
  camera sees it (the ultra-wide lens at 0.7 m, 1.5–2.5 m from the fence, a slow walk), safely staging faults on an
  electric fence, and running a ground model over the video. On a simulated walk, ground-v0.2 raised 8 alerts for
  the 8 faults, none false.
- **`tools/video_eval.py --class-conf`**: a threshold per fault class, as `ugv_alerts` on the robot
  (`fallen_post=0.5`). The drone's path is unchanged.
- **ground-v0.2, a candidate** ([run record](ml/runs/ground-v0.2)): ground-v0.1 fine-tuned with 1,500 more frames
  from 6 enclosures full of fallen posts (`make_ground_dataset.sh --focus post_down --posts-down 4-6`), 908 fallen
  posts in training instead of 372. Offline it beats ground-v0.1 everywhere the alerts look: test mAP50 0.979
  (0.957), fallen posts kept at conf 0.7 on the test forests 82% (52%), and on the four patrols every fault found
  with every class from 0.7, 29 of 29 (25 of 29), 0 false alerts. It becomes the default after live patrols.
- **`tools/train_with_breaks.py` stops for its breaks when started detached.** A shell without job control starts a
  background job with Ctrl+C ignored, and the training inherited that: ground-v0.2 ran epochs 3–8 without a break.
  It now resets the signal, and terminates a run that ignores the stop.
- **The ground model table** shows the patrols of all four forests (`tools/model_registry.py`), and a model can be a
  `candidate`: better offline, waiting for live tests.
- **ground-v0.1 on three new forests** ([run record](ml/runs/ground-v0.1)): `make_ground_dataset.sh --patrol
  --patrol-seed S` renders the patrol of a random forest never trained on. Seeds 700–702, offline with the live
  alert rule: 24 of 24 faults, 0 false alerts. With every fault at 0.7: 20 of 24, all four misses fallen posts.

## v0.13.0 · 2026-11-25 · the ground robot finds the faults: 50 of 50 in 10 live patrols

- **Real fence video** ([docs/drone-video.md](docs/drone-video.md)): `tools/video_eval.py` runs a fence model over a
  drone video, such as one from a DJI Mini 4 Pro, with the Jetson's alert rule (5 of 8 frames, conf 0.7). With DJI's
  subtitle file each alert gets a position on the ground; without it, frames alone confirm. It writes an annotated
  video, the alerts with map links and the frame of each. Tested on a simulated mission turned into a DJI-style video:
  the same 5 alerts on 3 faults, none false, as `tools/eval_mission.py`. `tools/confirm.py` takes the camera's
  geometry (`cam=`), like the ROS 2 copy.
- **Ground-view detector ground-v0.1** ([run record](ml/runs/ground-v0.1)): model-v0.5 fine-tuned for 10 epochs on
  3,600 frames from the robot's camera in random forests. Test enclosures mAP50 0.957 (model-v0.5: 0.040).
  **Live on the Jetson, 10 patrols in a row: 50 of 50 faults found, 0 false alerts** (offline, on the patrol
  frames: 5 of 5, 0 false; model-v0.5: 2 of 5, 19 false). The fallen post is the thin margin.
- **Fault alerts on the ground robot** (`./ros.sh ugv … detect:=true`): the detector on the side camera (TensorRT)
  and `ugv_alerts`, which confirms 5 of 8 frames taken 0.5 m of travel apart at the same spot on the fence, from
  the SLAM pose. Fallen posts count from conf 0.5, the others from 0.7: at 0.7 ground-v0.1 kept only half the
  fallen posts of its held-out forests, and the first live patrols missed F3. `tools/ugv_eval.py` scores the
  alerts and the steps near each fault; `tools/ugv_series.sh` passes launch arguments.
- **Ground-view dataset** for the robot's side camera: `tools/make_ground_dataset.sh` renders random forests (frames
  `G..` for train and val, `T..` for test) and the patrol of the real forest; `tools/ground_patrol_eval.py` scores a
  model on that patrol, as the alert chain would. model-v0.5 on it: 2 of 5 faults, 19 false alerts.
- **Model registry:** `ml/models.json` gets `ground_models` and `ml/README.md` a table for them
  (`tools/model_registry.py` validates both lists); release track `ground-vX.Y` in `tools/release_notes.py`. The
  v0.12.0 notes get the platform track's **Models:** line and "Install or run" heading.
- README in nine languages and the project page: the ground robot's fault alerts, v0.13 on the timeline.

## v0.12.0 · 2026-11-22 · a ground robot under the trees: LiDAR SLAM, 10 of 10 loops

- **Ground robot (UGV), phase 0: simulation** ([docs/ugv.md](docs/ugv.md)). A ground robot patrols a fenced forest
  enclosure, where the drone cannot see the fence and GNSS is poor. The Mac plays the robot's body and the Jetson
  runs its brain.
  - **World:** `forest.json` → `sim/gen_forest.py`. 500 m of fence with 5 faults, 880 trees, a cleared route strip
    with pinch points, bushes, logs and rocks, and a clearing. It reuses the pasture's fence and fault code.
  - **Robot:** a 4×4 skid steer with a 16-beam 3D LiDAR, a side camera at the fence and an IMU. Tyre friction is
    calibrated with `tools/ugv_calibrate.py`.
  - **Relay** (`tools/ugv_relay.py`, `./ugv.sh`): serves the robot to the Jetson over TCP and adds two error models.
    GNSS degrades with the sky the crowns hide. Wheel odometry gets scale and heading errors, only while the robot
    moves.
  - **ROS 2** (`./ros.sh ugv tcp://<mac>:5611`): `ugv_bridge` publishes `/ugv/*` (point cloud, IMU, odometry, GNSS,
    camera, route, fence, faults) and ground truth for scoring; `ugv_patrol` follows the route with pure pursuit, a
    LiDAR stop and turning on the spot at sharp corners.
  - **Tools:** a Foxglove layout (`ros2/foxglove/ugv-layout.json`) and `tools/ugv_eval.py`, which scores a patrol
    from the relay's log.
  - **Without SLAM:** on ground truth the robot completes the 516 m loop (99.8% in 762 s, at most 0.31 m off the
    route). On wheel odometry with 1% error it stops at the first tight spot (95 m and 107 m in two patrols). Under
    the canopy GNSS is 5 m off on median and 10 m at the 95th percentile.
- **LiDAR SLAM, teach and repeat** ([docs/ugv.md](docs/ugv.md#slam-teach-and-repeat)).
  - **Docker image:** pointcloud_to_laserscan, slam_toolbox, robot_localization and nav2_map_server. KISS-ICP has no
    Humble arm64 package.
  - **Teach:** `./ros.sh ugv … slam:=mapping` maps while driving. 10 s after the loop it saves the map and the route as
    the map sees it (the pose graph after the loop closed).
  - **Repeat:** `slam:=localization pose:=slam` patrols on the SLAM pose along that route, so the map's own warp
    cancels out.
  - **One clock:** every sample carries Gazebo's simulation time, and `ugv_bridge` publishes `/clock`. Stamping on
    arrival had made SLAM's heading drift on every turn.
  - **Outdoor tuning of slam_toolbox:** scans count for more against the odometry, a larger local map, and a 15 m
    loop-closure search.
  - **Scoring:** `ugv_eval` scores the SLAM pose against the truth and reports link gaps, so a stalled Wi-Fi link
    shows in the score instead of looking like a SLAM failure.
  - **CPU on the Orin Nano:** the ground-robot stack went from 327% to 119% of one core (of six) with the same
    accuracy. Changes: a lighter localisation config (194% → 39%); the bridge hands byte arrays to rclpy instead of
    `bytes`, which rclpy checks byte by byte, and publishes the trails every 2 s (77% → 33%); the stats node skips the
    high-rate and bulky topics. `./ros.sh cpu [SECONDS]` measures it.
  - **Measured: 10 of 10 loops.** `tools/ugv_series.sh N` runs N repeat patrols unattended, each from a clean start.
    A series of 8 completed the loop 8 of 8 times: 99.7–99.8% in 717–751 s, 0.18–0.19 m p95 off the true route,
    SLAM 0.25–0.27 m median and under 1 m throughout, no link gaps, no obstacle stops, 5 of 5 faults through the
    camera's view in every patrol. With repeats 2 and 3: 10 of 10, so the phase 0 goal of 9 of 10 is met.
  - **The map:** 0.10 m on median from each true trunk centre to the nearest occupied cell (739 trunks).
- **Pictures** in docs/ugv.md, all made from logs or by listening to Gazebo:
  - `tools/ugv_figures.py`: a patrol from above (true path, SLAM, wheel odometry) and each estimate's error along
    the loop;
  - `tools/ugv_lidar_view.sh`: the LiDAR point cloud in 3D while a patrol drives, or with `--sweep`, with no patrol
    and no Jetson (`tools/ugv_lidar_sweep.py`): the whole loop, one scan, and each fault;
  - `tools/ugv_slam_map.sh`: the SLAM map against the true forest (`ros2/grab_map.py` saves `/map` on the Jetson).
- **README in nine languages and the project page:** a section and a card for the ground robot, and the roadmap.
- **GPS at 0,0 under a 3D fix, fixed.** gpsd 3.22 drives the u-blox 7 (PROTVER 14) in binary mode and asks it only for
  NAV-SOL, which carries an ECEF position that gpsd does not convert: TPV reported a 3D fix at lat 0, lon 0 (or the last
  lat/lon it saw) while the receiver's own NAV-POSLLH and NAV-PVT were right. The receiver keeps its message settings
  only in RAM, so the fix lives in the readers:
  - the panel's device hub (`jetson/panel/hub.py`) checks gpsd's lat/lon against the ECEF position in the same report.
    When they differ by more than 50 m on a u-blox, it asks gpsd to turn NAV-POSLLH on (at most every 30 s) and
    reports no position until they agree. Field mode takes its fix from the hub, so it gets the same check;
  - the ROS 2 node `gpsd_gps` makes the same check and publishes no fix instead of a wrong position. It never writes
    to the receiver.

## v0.11.0 · 2026-11-21 · model-v0.5 is the default: no false alerts in flight

- **model-v0.5**, fine-tuned from v0.4 on 9,600 frames posed like the inspection flight and compressed like the
  camera stream. It is the default for everything: `./ros.sh demo` (replay), `./ros.sh demo tcp://…` (live Gazebo),
  the ROS 2 detector's `engine` and field mode in the panel. v0.3 and v0.4 are retired and stay selectable.
  - **Live on the Jetson (TensorRT FP16, 3.65 ms per frame):** 3 of 3 faults and **0 false alerts** in both looks
    (v0.4: 13 classic, 6 rich).
  - **Recorded mission replay:** 0 false alerts (v0.3: 6, v0.4: 12); 1 false broken-wire frame at conf ≥ 0.7 (v0.4:
    257).
  - **Held-out PNG sets:** as v0.4 (test mAP50 0.937 in both looks).
- **Why v0.4 flew worse than it tested:** the camera stream is MJPEG (`-q:v 4`, 4:2:0). Compressed the same way,
  synthetic flight frames give v0.3 and v0.4 8.2% and 14.8% false broken-wire frames, against 7.7% and 12.9% in the
  recorded flight. As PNG they give 1.0% and 0.2%.
- **Data tools:**
  - `tools/flight_poses_from_ulog.py` measures the flight's camera pitch, offset, heading and roll in PX4 logs
    (`ml/flight_poses.json`: camera 48–67° down, median 58°, 2.4 m outside the fence);
  - `make_dataset.py --style v4` renders farms from those poses along each farm's route (`--flight-share`);
  - `tools/jpeg_like_stream.py` makes dataset copies compressed like the stream;
  - `tools/eval_sets.py` reads `.jpg` sets and reports `wb_false`, the share of frames with a false broken wire;
  - `tools/train_with_breaks.py` trains in sessions with cooling breaks.
- **Registry:** model-v0.5, its 12 new datasets and the run record (`ml/runs/model-v0.5/`); a third benchmark file,
  `ml/benchmark/stream.json`, with 8 stream-like sets for v0.3 to v0.5.
- `tools/release_notes.py` accepts draft notes for a release that has no tag yet.
- **One benchmark for every model** (`ml/benchmark/`): model-v0.1 to v0.4 on the same 9 held-out sets in both world
  looks, and on the same recorded mission replayed through the live 5-of-8 confirmation. model-v0.2 reproduces its
  published numbers exactly; model-v0.1 is scored from its ONNX export.
- **Charts** from the registry (`tools/model_charts.py`):
  - `docs/img/model-evolution.png` shows every model on that benchmark, with one copy per model highlighted for its
    release page;
  - `docs/img/release-map.png` shows the platform and model releases over time, and which model each platform
    release used.
- **Consistent releases:**
  - every release from v0.1.0 to v0.10.0 and model-v0.1 to model-v0.4 now has its text in
    `docs/release-notes/<tag>.md`, on one template per track;
  - images are pinned to a commit, and every attached file is listed with its SHA-256;
  - `tools/release_notes.py` checks the files and publishes or verifies them with `gh`.
- `tools/eval_mission.py`: `--imgsz` for a static-shape ONNX export, and the live setting in the results.

## v0.10.0 · 2026-11-20 · model-v0.4 (both world looks) and a model registry

- **model-v0.4**, fine-tuned from v0.3 on 7,200 frames: half in the rich look, half classic, with re-fly close-ups.
  - **Held-out tests:**
    - Rich look, test seeds: mAP50 0.710 → 0.938, broken-wire recall 0.14 → 0.68.
    - Classic look, test seeds: 0.911 → 0.938.
  - **Live on the Jetson (TensorRT FP16, 3.6 ms per frame):**
    - Rich world: 3 of 3 faults with 6 false alerts, where v0.3 found 1 of 3.
    - Classic mission: 13 false broken-wire alerts against v0.3's 5. They sit at corner posts and along the dead
      strand. The offline tests did not show this.
  - **Where each model runs:**
    - v0.4 runs the live Gazebo flights.
    - v0.3 stays the default: the ROS 2 detector, the classic replay demo and field mode.
- **Model and dataset registry (`ml/`):**
  - `models.json` lists every model from v0.1 to v0.4: status, data, code commit, training, offline and live
    scores, and the sha256 of every file. The hashes were checked against the releases, the Mac and the Jetson.
  - `datasets.json` holds the generator command and commit, seeds and splits. Test splits are marked, and the
    validator refuses a model trained on one.
  - `runs/model-v0.4/` keeps the arguments, scores per epoch, the data mix, held-out and replay scores, the live
    flights alert by alert, and the engine build.
  - `tools/model_registry.py` validates the registries, writes the table in `ml/README.md` and checks local model
    files against the hashes.
- **Tools:**
  - `make_dataset.py --look rich` and `--style v3` (re-fly poses).
  - `tools/mix_dataset.py` for training mixes.
  - `tools/eval_sets.py` scores the held-out sets of both looks.
  - `train_yolo.py --resume` continues a paused run.
- **Jetson:**
  - `ros.sh demo tcp://…` picks model-v0.4, and `engine:=` overrides it.
  - `ros.sh doctor` checks both engines.
  - The detector overlay names the model.
  - The panel lists v0.4 for field mode.
- **Docs:** the v0.4 section and the v0.5 plan in `docs/retraining-log.md`, an updated model card, and a map of where
  the false alerts fall.

## v0.9.0 · 2026-11-20 · a nicer simulation: the "rich" look

- **New default look** (`sim/gen_world.py`):
  - a sky with clouds, a low and warm afternoon sun with a cool fill light;
  - textured grass (tileable albedo and normal maps from `tools/make_textures.py`, no downloaded assets);
  - rolling hills around the farm, with a valley for the road (`models/pasture_ground`, mesh generated from
    `fence.json`). The paddock and farmyard stay flat, so the flight, the physics and the alert projection are
    unchanged;
  - about 160 trees (broadleaf and fir) on the hills, small woods, a hedgerow along the road;
  - a farmyard: barn with white trim and doors, silo, hay bales and a farmhouse;
  - rounder cows (Holstein patches, ears, muzzle, udder, tail) and fleecy sheep.
- **`--look classic`** (or `GARDIAN_LOOK`, or `"look"` in `fence.json`) brings back the original world.
  `tools/make_dataset.py` stays on the classic look, and with it the classic world is byte-identical to before.
- **`tools/snap_world.sh`** renders still images from fixed viewpoints and prints the ground colour the inspection
  camera sees.
- **Measured.** Flight time and camera rate are unchanged (2:34, 14.6 fps).
  - model-v0.3 was trained on the classic look. On the rich world it found 1 of 3 real faults (0 false alerts),
    against 3 of 3 (5 false alerts) on the classic world.
  - Use `--look classic` for live detector tests until v0.4 is trained on both looks. Details are in
    `docs/retraining-log.md`.
- **Media:** the README and project-page images were regenerated in the new look with `./start.sh demo`, in English.

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
- Foxglove layout `ros2/foxglove/querra-layout.json`
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
