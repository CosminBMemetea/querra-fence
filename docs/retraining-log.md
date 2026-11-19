# Retraining log: fence detector

This log follows the fence detector from version to version. Each entry records what we trained, how it scored, what it
got wrong on the Jetson, and what we changed because of it. Model files are attached to the GitHub releases
(`model-v0.x`). The model card is in [model-card.md](model-card.md).

**Classes:** `post`, `wire`, `wire_break`, `fallen_post`, `branch`, `cow`, `sheep`

**How we test.** The trained model is exported to ONNX and built into a TensorRT FP16 engine on the Jetson Orin Nano.
The Jetson then runs it on the drone camera, which `tools/cam_stream.py` streams from Gazebo over the LAN while PX4
flies the inspection mission. Every frame is logged with the simulated GPS. A frame counts toward a fault when the
drone is within 30 m of it. A detection counts as a **false alarm** when the drone is more than 45 m from the real fault
of that class.

## v0.1 · preliminary checkpoint (`model-v0.1`)

- **Data:** 4,200 frames rendered from 12 random farms by `tools/make_dataset.py`, with labels computed from Gazebo
  ground truth (no hand labelling). 10 farms (3,500 frames) for training, 2 held-out farms (700 frames) for validation.
- **Training:** YOLO11n at 640 px, CPU. This is the checkpoint after **epoch 2** of the run that became v0.2.
  Exported early to test the Jetson pipeline end to end.
- **Validation:** mAP50 **0.72** (all classes).
- **On the Jetson** (60 s of the simulated mission, 874 frames at 14.6 fps):

| Fault | Frames within 30 m | Frames detected | Best confidence |
|---|---|---|---|
| F1 broken wire | 228 | 46 (20%) | 0.78 |
| F2 fallen post | 240 | 7 (3%) | 0.63 |
| F3 branch | not reached in the 60 s window | | |

- **False alarms:** 72 frames flagged `wire_break` more than 45 m from F1.
- **Takeaway:** the whole loop works (Gazebo → LAN → Jetson → TensorRT → GPS-tagged log). The model was undertrained,
  especially on the rare fault classes.

![v0.1 on the Jetson near F1](img/v0.1-jetson-prelim-F1.jpg)

![Auto-generated labels on training frames](img/dataset-auto-labels.jpg)

## v0.2 · first full model (`model-v0.2`)

- **Data:** the same 4,200 frames (12 farms: 10 train, 2 held-out validation). The farms vary the fence shape, post
  spacing, wire heights, faults (2–3 broken wires, 1–2 fallen posts, 1–2 branches), herd, sun angle and grass colour.
  The camera varies in height (5–20 m), tilt (35–80°), heading and roll.

| Class | Train boxes | Val boxes |
|---|---|---|
| post | 11,458 | 2,559 |
| wire | 13,148 | 2,886 |
| wire_break | 956 | 141 |
| fallen_post | 444 | 57 |
| branch | 403 | 117 |
| cow | 1,624 | 234 |
| sheep | 1,173 | 169 |

- **Training:** YOLO11n, 25 epochs, 640 px, batch 16, CPU (about 2 hours). Mosaic augmentation, turned off for the
  last 3 epochs.
- **Validation (2 held-out farms):**

| Class | mAP50 | mAP50-95 |
|---|---|---|
| post | 0.968 | 0.846 |
| wire | 0.977 | 0.878 |
| wire_break | 0.818 | 0.604 |
| fallen_post | 0.916 | 0.789 |
| branch | 0.934 | 0.636 |
| cow | 0.915 | 0.756 |
| sheep | 0.922 | 0.743 |
| **all** | **0.921** | **0.750** |

![Training curves](img/v0.2-training-curves.jpg)

- **On the Jetson** (TensorRT FP16, input 640×416):
  - `trtexec` measures 4.7 ms per frame on the GPU.
  - In the pipeline the detector takes 20.8 ms per frame (29.4 ms at p95), including pre- and post-processing.
  - The full mission ran at **13.3 fps** against the camera's 15. Gazebo to Jetson latency is about 13 ms.
  - Full flight: 165 s, 2,196 frames.

| Fault | Frames within 30 m | Frames detected | Best confidence |
|---|---|---|---|
| F1 broken wire | 235 | 113 (48%) | 0.94 |
| F2 fallen post | 223 | 58 (26%) | 0.96 |
| F3 branch | 162 | 14 (9%) | 0.84 |

![v0.2 on the Jetson: F1 broken wire, F2 fallen post, F3 branch, and a false broken wire](img/v0.2-jetson-faults.jpg)

### What v0.2 missed: false broken-wire alarms

All three faults were found, and `fallen_post` and `branch` produced **no** false alarms. But `wire_break` fired in
**385 frames** far from F1 (confidence ≥ 0.5).

**Root cause.** After a wire breaks, the simulation draws the rest of that strand in grey ("dead"). From 12 m a grey
strand is almost invisible, so an intact fence with a dead top wire looks like "one wire is missing", which is what a
break looks like. The training farms did contain dead wire labelled `wire`, but too few examples, and always in the
same grey. A real dead wire looks exactly like a live one, so this is partly a simulation artefact the model learned.

![False broken wire: intact fence with a grey (dead) top strand](img/v0.2-false-wire-break.jpg)

A higher confidence threshold trades false alarms for missed detections. It is not a fix:

| Threshold | False frames (>45 m from F1) | Frames detecting F1 (<30 m) |
|---|---|---|
| 0.5 | 385 | 85 |
| 0.6 | 292 | 65 |
| 0.7 | 192 | 46 |
| 0.8 | 89 | 16 |

## v0.3 · targeted data for the false broken wire (`model-v0.3`)

**What we changed.**

1. **More of the confusing data** (`tools/make_dataset.py --style v2`). 8 new training farms (2,400 frames) with 3–4
   breaks each, so long stretches of fence carry a dead strand. The dead strand is drawn in random colours (grey, the
   live yellow, dull or dark) and is always labelled `wire`. Breaks come in three shapes (ends hanging, snapped wire on
   the grass, one end still tied), and 60% of the poses imitate the inspection flight.
2. **Fine-tuned from v0.2** for 10 epochs on 4,800 frames: the 2,400 new frames plus 2,400 random v0.2 training frames,
   so the model keeps what it knew. CPU, AdamW (lr 0.0009), mosaic off for the last 3 epochs. Best epoch: 9.
3. **Evaluated on data never used for training:**
   - the 2 old validation farms (700 frames)
   - 2 new validation farms in the v2 style (600 frames)
   - a **test set of 3 new farm seeds** (140–142, 750 frames), never used for training or model selection
   - 400 frames rendered from the mission pasture itself (`fence.json`)
4. **Multi-frame GPS confirmation** (`tools/confirm.py`). Every fault box is placed on the ground using GPS, altitude,
   heading and the camera angle. An alert is raised only when N of the last M frames put the same fault class within
   5 m. One spot gives one alert.

![v2 training frames: dead strands in other colours labelled wire (yellow), breaks in red](img/v0.3-dataset-v2.jpg)

### Scores, v0.2 → v0.3 (mAP50)

| Set | All classes | `wire_break` | `wire_break` precision / recall |
|---|---|---|---|
| Old validation farms (700) | 0.921 → 0.916 | 0.818 → 0.778 | 0.86 / 0.73 → 0.77 / 0.74 |
| New validation farms, v2 style (600) | 0.913 → **0.932** | 0.556 → **0.681** | 0.67 / 0.46 → 0.71 / 0.60 |
| **Held-out test, new seeds (750)** | 0.897 → **0.912** | 0.577 → **0.684** | 0.80 / 0.42 → 0.70 / 0.61 |
| Mission pasture frames (400) | 0.956 → 0.958 | 0.805 → 0.775 | 0.79 / 0.79 → 0.66 / 0.81 |

The other classes stayed within ±0.02. v0.2 had only been tested on farms like its training data. On the new farms with
many dead strands it found fewer than half the breaks (recall 0.42), and v0.3 raises that to 0.61. The cost is
precision: v0.3 calls `wire_break` more readily, which shows on the old farms and the mission pasture.

### The simulated mission, v0.2 → v0.3

The same recorded flight (`tools/cam_record.py`: 1,986 frames at 12 m) was replayed through both models with
`tools/eval_mission.py`. This was PyTorch on CPU, not the Jetson, so the absolute counts differ from the 385 measured on
the Jetson for v0.2. Compare the two columns with each other.

| | v0.2 | v0.3 |
|---|---|---|
| F1 broken wire: frames that saw it (of 249 nearby) | 130 | 121 |
| F2 fallen post (of 242) | 67 | 65 |
| F3 branch (of 242) | 66 | 66 |
| False `wire_break` frames (> 45 m from F1), conf ≥ 0.5 | 485 | 413 (−15%) |
| False `wire_break` frames, conf ≥ 0.7 | 242 | 153 (−37%) |
| False `fallen_post` / `branch` frames, conf ≥ 0.5 | 2 / 0 | 1 / 0 |

**Alerts** (one per spot on the ground) are what the farmer sees. All settings below still alert on all three real
faults.

| Confirmation | v0.2 false alerts | v0.3 false alerts |
|---|---|---|
| None (every frame, conf ≥ 0.5) | 33 | 31 |
| 3 of 5 frames within 5 m, conf ≥ 0.5 | 27 | 21 |
| 3 of 5 frames, conf ≥ 0.7 | 20 | 9 |
| **5 of 8 frames, conf ≥ 0.7** | 11 | **6** |

Better data alone removed few false frames, and confirmation alone removed few alerts. Combined, false alerts fell from
33 to 6 (−82%), and all three faults were still found. 5 of 8 frames at conf ≥ 0.7 is now the default in `tools/confirm.py` and on the Jetson.

### What v0.3 still misses

![Remaining false broken wires in the mission pasture](img/v0.3-remaining-false-wire-break.jpg)

The remaining false `wire_break` boxes in the mission pasture sit where the yellow live strand and the thin grey dead
strand of the same fence run side by side, or swap at a post. From 12 m that looks like a strand ending. The random v2
farms taught the general case (validation and test improved a lot). They did not cover this exact look: mission
lighting and a dead strand running for hundreds of metres.

## v0.4 · planned

- **Hard negatives from flights.** Record missions over new farm seeds (never the test seeds). Add every confident
  false `wire_break` frame to the training data with its true labels.
- **Live and dead strands side by side** for long runs, and more lighting set-ups.
- **Real frames.** Fine-tune on photos from the field mode recorder (`field.sh`). Reality matters more than any
  simulation artefact.
