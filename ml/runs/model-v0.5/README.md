# model-v0.5 · inspection-flight poses and the camera stream's JPEG

| | |
|---|---|
| Status | **default** from platform v0.11.0: the replay demo, live Gazebo flights, the ROS 2 detector and field mode |
| Date | 2026-11-21 |
| Parent | model-v0.4 (fine-tuned) |
| Code | `38b8990` (flight poses, dataset generator style v4, stream-like JPEG copies, eval and training scripts as used) |
| Files | `fence-yolo11n-v0.5.pt`, `.onnx` (416×640), Jetson engine `fence-yolo11n-v0.5-fp16.engine`; sha256 in [models.json](../../models.json) |

## Why

model-v0.4 scored better than v0.3 on every held-out set, then raised **13 false broken-wire alerts** in the live
classic flight (v0.3: 5). Most sat at corner posts and along the grey dead strand. The run record of v0.4 blamed the
poses. The search for the cause found two things.

**1. The camera stream's JPEG compression.** The models were trained on lossless PNG renders. In flight, Gazebo's
camera reaches the Jetson as MJPEG (`tools/cam_stream.py`: ffmpeg `-q:v 4`, 4:2:0 colour). The two wires of the fence
are 1–2 px wide at 12 m; JPEG blocks and halved colour resolution break them into pieces that look like a break. The
same synthetic frames, scored with and without the stream's compression:

| Frames with a false broken wire, conf ≥ 0.7 | model-v0.3 | model-v0.4 |
|---|---|---|
| Synthetic flight over the mission pasture, PNG | 1.0% | 0.2% |
| The same frames, JPEG like the stream | **8.2%** | **14.8%** |
| The recorded mission flight (real stream, 1,986 frames) | **7.7%** | **12.9%** |
| Old mission-pasture test set (random poses), JPEG like the stream | 15.2% | 22.8% |

Compressed like the stream and posed like the flight, the synthetic frames predict the recorded flight within about one
percentage point, for both models. As PNG they predict almost nothing. v0.4 is more sensitive to JPEG than v0.3, which
is why it looked better offline and flew worse.

**2. How the drone really looks at the fence.** The camera is fixed at 55° down, but the drone noses down to fly, so
the camera looks steeper. `tools/flight_poses_from_ulog.py` measured the AUTO_MISSION part of two PX4 SITL logs over
the mission fence (2,830 samples, [flight_poses.json](../../flight_poses.json)):

| | 5% | median | 95% |
|---|---|---|---|
| Distance outside the fence | 1.6 m | 2.4 m | 2.7 m |
| Camera pitch (55° minus body pitch) | 48.5° | 57.6° | 67.1° |
| Roll on straights / in corners | −2.9° / −11.7° | 0.0° / −0.6° | 3.1° / 4.9° |
| Heading against the route, on straights | −3.4° | −0.4° | 2.2° |
| Altitude, speed | 11.9 m, 3.0 m/s | 12.0 m, 3.9 m/s | 12.0 m, 4.5 m/s |

48% of the samples are within 12 m of a corner. A first try fitted the pitch by rendering the world at the recorded
positions and comparing images. It returned 46° and was wrong: the logged position lags the image, and a shorter
look ahead traded against a flatter pitch. The flight log is the measurement; image fitting is not used.

## Data

| Dataset ([datasets.json](../../datasets.json)) | Look | Split | Frames in the mix |
|---|---|---|---|
| `fence_yolo_flight_classic_stream`: 8 new farms, flight poses (style v4) | classic | train | 2,400 |
| `fence_yolo_flight_rich_stream`: 8 new farms, flight poses (style v4) | rich | train | 2,400 |
| `fence_yolo_rich_stream` (v0.4's rich farms) | rich | train | 2,000 of 3,600 |
| `fence_yolo_v3c_stream` (v0.4's re-fly close-ups) | classic | train | 1,000 of 1,200 |
| `fence_yolo_v2_stream` (dead strands, from v0.3) | classic | train | 1,000 of 2,400 |
| `fence_yolo_stream` (the original farms) | classic | train | 800 of 3,500 |
| **Training total** | | | **9,600** |
| `fence_yolo_flight_classic_q4` + `fence_yolo_flight_rich_q4` + `fence_yolo_v2` validation farms | both | val | 1,800 |

- **Style v4** (`tools/make_dataset.py --style v4`). 70% of the poses fly the farm's own inspection route at an attitude
  drawn from the measured flight poses: the offset, pitch, roll and heading error, half of them near a corner, and 10%
  flown the other way round. The other 30% are v3 poses: random views and re-fly close-ups.
- **Stream-like copies** (`tools/jpeg_like_stream.py`). 75% of the new frames and 50% of the old ones are compressed
  like the stream, at a random quality (`-q:v` 2, 3, 4, 5, 6 or 8). The rest stay PNG. 6,119 of the 9,600 training
  frames are JPEG.
- **Validation** is JPEG at `-q:v 4`, the stream's own setting ([data.yaml](data.yaml)).

## Training

YOLO11n fine-tuned from model-v0.4 for 6 epochs at 640 px, batch 16, on the laptop CPU (Apple M2, 8 GB). AdamW with
lr 0.000909 and 3 warm-up epochs, as chosen by Ultralytics; mosaic off for the last 3 epochs.
`tools/train_with_breaks.py` ran it in 3 sessions of 2 epochs with 15-minute cooling breaks, resuming with the
optimizer state: **3.4 h** of training. The last epoch was the best and is the model ([args.yaml](args.yaml),
[results.csv](results.csv)).

| Epoch | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|
| 1 | 0.925 | 0.747 | 0.925 | 0.866 |
| 2 | 0.920 | 0.732 | 0.931 | 0.866 |
| 3 | 0.929 | 0.747 | 0.941 | 0.871 |
| 4 | 0.941 | 0.760 | 0.936 | 0.897 |
| 5 | 0.943 | 0.763 | 0.941 | 0.895 |
| **6** | **0.952** | **0.785** | 0.952 | 0.905 |

Validation set: JPEG flight farms of both looks and the v2 validation farms (1,800 frames); not comparable with
v0.4's PNG validation set. Final per-class mAP50: post 0.990, wire 0.992, `wire_break` 0.801 (precision 0.91,
recall 0.66), `fallen_post` 0.987, `branch` 0.972, cow 0.954, sheep 0.966.

## Offline scores

### Stream sets: posed like the flight, compressed like the stream

`tools/eval_sets.py --sets …`, PyTorch on CPU ([eval_stream.json](eval_stream.json),
[benchmark/stream.json](../../benchmark/stream.json)). None of these frames was used for training. `wb_false` is the
share of frames with a broken wire at conf ≥ 0.7 that overlaps no labelled break.

| Set | Frames | mAP50 v0.3 / v0.4 / **v0.5** | `wire_break` mAP50 | `wb_false` |
|---|---|---|---|---|
| **classic flight, mission pasture, JPEG** | 400 | 0.896 / 0.884 / **0.963** | 0.41 / 0.26 / **0.79** | 8.2% / 14.8% / **0.0%** |
| **rich flight, mission pasture, JPEG** | 400 | 0.591 / 0.887 / **0.954** | 0.17 / 0.34 / **0.77** | 0.0% / 9.8% / **0.0%** |
| classic flight, test seeds 160–162, JPEG | 750 | 0.850 / 0.860 / **0.926** | 0.21 / 0.27 / **0.62** | 7.3% / 6.8% / **0.4%** |
| rich flight, test seeds 160–162, JPEG | 750 | 0.592 / 0.856 / **0.914** | 0.04 / 0.21 / **0.52** | 0.1% / 9.2% / **0.3%** |
| classic, test seeds 140–142, JPEG | 750 | 0.819 / 0.834 / **0.910** | 0.27 / 0.29 / **0.67** | 15.5% / 12.9% / **1.2%** |
| rich, test seeds 140–142, JPEG | 750 | 0.694 / 0.862 / **0.920** | 0.16 / 0.40 / **0.71** | 0.1% / 9.2% / **0.4%** |
| classic flight, mission pasture, PNG | 400 | 0.953 / 0.969 / **0.974** | 0.79 / 0.84 / **0.86** | 1.0% / 0.2% / **0.0%** |
| rich flight, mission pasture, PNG | 400 | 0.620 / 0.966 / **0.969** | 0.17 / 0.84 / **0.87** | 0.0% / 0.0% / **0.0%** |

### The shared held-out sets (PNG)

The same 9 sets as every model before ([eval_heldout.json](eval_heldout.json),
[benchmark/heldout.json](../../benchmark/heldout.json)).

| Set | Frames | mAP50 v0.4 → v0.5 | `wire_break` mAP50 | `wire_break` precision / recall |
|---|---|---|---|---|
| classic: old validation farms | 700 | 0.927 → 0.928 | 0.834 → 0.850 | 0.86 / 0.75 → 0.88 / 0.74 |
| classic: v2 validation farms | 600 | 0.956 → 0.956 | 0.818 → 0.816 | 0.87 / 0.67 → 0.95 / 0.66 |
| **classic: test seeds 140–142** | 750 | 0.938 → 0.937 | 0.822 → 0.808 | 0.85 / 0.69 → 0.89 / 0.65 |
| classic: mission pasture | 400 | 0.981 → 0.976 | 0.900 → 0.865 | 0.93 / 0.79 → 1.00 / 0.72 |
| classic: re-fly close-ups | 400 | 0.981 → 0.982 | 0.963 → 0.972 | 0.97 / 0.88 → 0.97 / 0.89 |
| rich: validation farms | 600 | 0.954 → 0.952 | 0.858 → 0.849 | 0.82 / 0.76 → 0.90 / 0.73 |
| **rich: test seeds 140–142** | 750 | 0.938 → 0.937 | 0.789 → 0.783 | 0.84 / 0.68 → 0.89 / 0.61 |
| rich: mission pasture | 400 | 0.977 → 0.976 | 0.877 → 0.865 | 0.87 / 0.84 → 0.97 / 0.74 |
| rich: re-fly close-ups | 400 | 0.984 → 0.987 | 0.968 → 0.969 | 0.98 / 0.89 → 0.98 / 0.89 |

On PNG, v0.5 scores like v0.4 (within ±0.01 mAP50; `wire_break` up to −0.035 on the mission pasture). It trades a
little broken-wire recall for precision: its `wire_break` precision is equal or higher on every set.

## The mission replay

The recorded classic mission (1,986 frames from the real stream) through `tools/eval_mission.py` and the live
confirmation, 5 of 8 frames at conf ≥ 0.7 ([mission_replay.json](mission_replay.json)).

| | model-v0.3 | model-v0.4 | **model-v0.5** |
|---|---|---|---|
| F1 broken wire: frames that saw it (of 249 nearby), best conf | 121, 0.93 | 147, 0.94 | **66, 0.87** |
| F2 fallen post (of 242) / F3 branch (of 242) | 65 / 66 | 66 / 62 | 68 / 64 |
| False `wire_break` frames, conf ≥ 0.5 | 413 | 551 | **9** |
| False `wire_break` frames, conf ≥ 0.7 | 153 | 257 | **1** |
| Confirmed alerts | 10: 3 faults + 6 false | 18: 3 faults + 12 false | **5: 3 faults + 0 false** |

## Live flights on the Jetson

Gazebo on the Mac streams the camera over the LAN. On the Jetson the TensorRT FP16 engine runs, alerts are confirmed
5 of 8 and placed with PX4's own pose over uXRCE-DDS. One mission per look, scored on the inspection part. An alert
is real when its class matches a fault within 15 m ([live/flights.json](live/flights.json), raw checks in
[live/](live)).

| World | model-v0.3 | model-v0.4 | **model-v0.5** |
|---|---|---|---|
| **rich** (the default look) | 1 of 3 faults, 0 false alerts | 3 of 3 faults, 6 false alerts | **3 of 3 faults, 0 false alerts** |
| classic | 3 of 3 faults, 5 false alerts | 3 of 3 faults, 13 false alerts | **3 of 3 faults, 0 false alerts** |

- **Classic:** three alerts, one per fault, 1.9 m (broken wire), 3.2 m (fallen post) and 4.1 m (branch) from the
  truth.
- **Rich:** four alerts. The fallen post was confirmed twice, 3.2 m and 5.0 m away (one fault, so 3 of 3 and no
  false alert).
- **Re-fly** (6 m altitude, 5 s hover over each alert):
  - It verified the broken wire (67 of 67 and 68 of 68 frames) and the fallen post (57 of 73; 56 of 56) in both
    looks. In the rich look the second fallen-post alert, 3.2 m away, was not seen up close (0 of 76).
  - It did not see the branch up close in either look (0 of 71, 0 of 74). Both branch alerts sat about 4 m from
    the branch, so it was at the edge of the hover view. v0.4's branch alerts were 1.4 m away and were verified.
  - In the rich look, while hovering over the fallen post, it raised one broken-wire alert 1.7 m from the post. The
    wires hang loose there. It came after the inspection, so it is not counted above.
- **Speed:** the engine runs at 3.65 ms per frame (`trtexec`: 292 inferences/s, [trtexec.txt](trtexec.txt)), the same
  as v0.4.

## Decision

**model-v0.5 is the default for everything** from platform v0.11.0: `./ros.sh demo` (the classic replay),
`./ros.sh demo tcp://…` (live Gazebo flights), the ROS 2 detector's `engine` default and field mode in the panel.
v0.3 and v0.4 are retired. They stay selectable with `engine:=` and in the panel.

- It is the first model with no false alert in any flight we have: the classic and rich live flights and the
  mission replay.
- On the PNG held-out sets it equals v0.4.
- Field mode on the real camera has no measured data with any model. The real camera's stream is MJPEG too, so the
  model trained on stream-like frames is the better bet.

## Known limits and next steps

- **Fewer frames see a broken wire.** In the replay, F1 is seen in 66 frames, against 147 for v0.4, and the best
  confidence drops from 0.94 to 0.87. The 5-of-8 confirmation still raises the alert in both live flights, but the
  margin is smaller. Next: more broken-wire examples at flight poses, or a lower per-frame threshold for
  `wire_break` once false frames stay rare.
- **Branch alerts sit about 4 m off**, so the re-fly misses the branch. Look at how a branch box on top of the wire is
  projected to the ground.
- **Loose wires on a fallen post look broken up close.** Label them, or let the re-fly accept a fallen post there.
- **The stream itself.** `-q:v 2` or 4:4:4 colour would keep the wires sharper, at about twice the bandwidth.
- **Real frames.** Everything here is simulated. The first real recordings from the field recorder come first.

## Files

| File | Content |
|---|---|
| [args.yaml](args.yaml) | Ultralytics arguments (as saved by the last resumed session) |
| [results.csv](results.csv) | Losses and validation metrics per epoch |
| [data.yaml](data.yaml) | The training mix (`tools/mix_dataset.py` command) |
| [eval_stream.json](eval_stream.json) | `tools/eval_sets.py`: 8 stream sets, v0.3, v0.4 and v0.5 |
| [eval_heldout.json](eval_heldout.json) | `tools/eval_sets.py`: the 9 shared held-out sets, v0.5 |
| [mission_replay.json](mission_replay.json) | `tools/eval_mission.py` on the recorded classic mission, v0.5 |
| [live/flights.json](live/flights.json) | Live flights: every alert with class, confidence, phase, nearest fault, verdict; re-fly reports |
| [live/*_px4_check.txt](live) | Raw live checks: PX4 pose against the simulator, alerts against the true faults |
| [trtexec.txt](trtexec.txt) | TensorRT FP16 engine build on the Jetson Orin Nano |
