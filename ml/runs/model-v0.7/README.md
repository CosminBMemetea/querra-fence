# model-v0.7 · negatives for broken wires (not adopted)

| | |
|---|---|
| Status | **not adopted**: model-v0.5 stays the default. Kept for comparison |
| Date | 2026-11-28 |
| Parent | model-v0.5 (fine-tuned) |
| Code | `e51b664` (`make_dataset.py --breaks 0 --corner-share 0.9`, refined alert positions, `--class-conf`) |
| Files | `fence-yolo11n-v0.7.pt`, `.onnx` (416×640); no Jetson engine; sha256 in [models.json](../../models.json) |

## Why

[model-v0.6](../model-v0.6) gained fallen posts on thin wire but raised false broken wires, and one confirmed false
alert at a corner post, where the two strands of a span line up in perspective. model-v0.7 tests the fix its run
proposed: **negatives** (flight frames near corners with every wire whole), plus the steel-wire and polywire frames
that taught fallen posts, and none of the rope and tape breaks that did not teach breaks.

## Data

| Dataset ([datasets.json](../../datasets.json)) | Split | Frames in the mix |
|---|---|---|
| model-v0.5's training mix (6 datasets, [its data](../model-v0.5#data)) | train | 9,600 |
| `drone_yolo_looks_stream`, steel-wire and polywire layouts only (no wire boxes) | train | 1,500 |
| **`drone_yolo_corners_stream`**: 8 new farms with no broken wire, 90% of poses within 12 m of a corner | train | 2,000 |
| **Training total** (8,774 JPEG like the stream) | | **13,100** |
| model-v0.5's validation farms (the same 1,800 frames) | val | 1,800 |

- **The corner farms** (seeds 364–371, style v4, 250 frames each, classic 264–267, rich 268–271): rendered with
  `--breaks 0`, which keeps each farm's other random draws (fallen posts, branches, animals), and `--corner-share 0.9`.
  Labels: post 5,366, wire 6,328, `wire_break` 0, `fallen_post` 142, `branch` 117.
- The mix and its command: [data.yaml](data.yaml).

## Training

YOLO11n fine-tuned from model-v0.5 for 8 epochs at 640 px, batch 8, on the M2's GPU (MPS); the same settings as
model-v0.6. 15-minute cooling breaks before training and after epochs 2, 4 and 6: **1.7 h of training**, 2.7 h with
the breaks. The last epoch was the best and is the model ([args.yaml](args.yaml), [results.csv](results.csv)).

| Epoch | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|
| 1 | 0.939 | 0.755 | 0.948 | 0.888 |
| 2 | 0.940 | 0.757 | 0.948 | 0.890 |
| 3 | 0.936 | 0.740 | 0.924 | 0.879 |
| 4 | 0.931 | 0.762 | 0.933 | 0.887 |
| 5 | 0.949 | 0.780 | 0.946 | 0.905 |
| 6 | 0.943 | 0.774 | 0.942 | 0.886 |
| 7 | 0.949 | 0.791 | 0.946 | 0.910 |
| **8** | **0.957** | **0.803** | 0.961 | 0.912 |

The validation set is model-v0.5's, so this compares: 0.957 against 0.952. Per class: post 0.991, wire 0.993,
`wire_break` 0.827 (precision 0.94, recall 0.67; v0.5: 0.801, 0.91, 0.66), `fallen_post` 0.989, `branch` 0.973,
cow 0.959, sheep 0.969. Validation scores the boxes at every confidence; the checks below count them from the alert
threshold, in frames with no break too, and there it went the other way.

## The checks that decide: false broken wires

### Stream sets

The 8 sets posed like the flight and compressed like the stream ([eval_stream.json](eval_stream.json),
[benchmark/stream.json](../../benchmark/stream.json)).

| Set | Frames | mAP50 v0.5 → **v0.7** | `wire_break` mAP50 | `wire_break` P / R | `wb_false` |
|---|---|---|---|---|---|
| **classic flight, mission pasture, JPEG** | 400 | 0.963 → 0.963 | 0.793 → 0.810 | 1.00 / 0.69 → 1.00 / 0.70 | 0.0% → 0.0% |
| **rich flight, mission pasture, JPEG** | 400 | 0.954 → 0.953 | 0.772 → 0.797 | 0.93 / 0.71 → 0.90 / 0.75 | 0.0% → **0.2%** |
| classic flight, test seeds 160–162, JPEG | 750 | 0.926 → 0.929 | 0.623 → 0.623 | 0.71 / 0.58 → 0.75 / 0.51 | 0.4% → **0.8%** |
| rich flight, test seeds 160–162, JPEG | 750 | 0.914 → 0.924 | 0.516 → 0.544 | 0.73 / 0.33 → 0.65 / 0.42 | 0.3% → **0.8%** |
| classic, test seeds 140–142, JPEG | 750 | 0.910 → 0.920 | 0.671 → 0.701 | 0.76 / 0.54 → 0.76 / 0.59 | 1.2% → **2.3%** |
| rich, test seeds 140–142, JPEG | 750 | 0.920 → 0.928 | 0.705 → 0.728 | 0.80 / 0.52 → 0.75 / 0.64 | 0.4% → **0.8%** |
| classic flight, mission pasture, PNG | 400 | 0.974 → 0.970 | 0.863 → 0.848 | 1.00 / 0.68 → 1.00 / 0.71 | 0.0% → 0.0% |
| rich flight, mission pasture, PNG | 400 | 0.969 → 0.969 | 0.867 → 0.869 | 1.00 / 0.78 → 1.00 / 0.75 | 0.0% → 0.0% |

The frames with a false break **double** on the four test sets (0.3–1.2% → 0.8–2.3%); on the classic farms of seeds
140–142 they are above model-v0.6's too (2.3% against 1.3%). The negatives did not lower them.

### The mission replay

The recorded classic mission (1,986 frames of the real stream), 5 of 8 frames from conf 0.7, alert positions refined
by every sighting ([mission_replay.json](mission_replay.json)).

| | model-v0.5 | model-v0.6 | **model-v0.7** |
|---|---|---|---|
| F1 broken wire: frames that saw it (of 249 nearby), best conf | 66, 0.87 | 73, 0.92 | 65, 0.91 |
| False `wire_break` frames, conf ≥ 0.5 / ≥ 0.7 | 9 / 1 | 35 / 15 | **24 / 8** |
| Confirmed alerts | 3: 3 faults + 0 false | 4: 3 faults + 1 false | **4: 3 faults + 1 false** |

The false alert is the same corner post as model-v0.6's, 57 m from F1. The corner negatives did not help there:
frames with a break box within 10 m of it, from 0.7, are 1 for model-v0.5, 5 for model-v0.6 and **6 for model-v0.7**
(best conf 0.75, 0.82, 0.84). With broken wires counted only from 0.75 the alert goes (3 alerts, 0 false), but 0.75
was chosen on this replay.

### A higher threshold does not fix it

Broken wires found (IoU 0.3) and frames with a false break on the 6 JPEG stream sets
([wb_thresholds.json](wb_thresholds.json)):

| Set | model-v0.5 from 0.7 | model-v0.7 from 0.7 | from 0.75 | from 0.8 |
|---|---|---|---|---|
| classic flight, mission pasture | 67%, 0.0% | 71%, 0.0% | 71%, 0.0% | 58%, 0.0% |
| rich flight, mission pasture | 50%, 0.0% | 71%, 0.2% | 62%, 0.0% | 54%, 0.0% |
| classic flight, test 160–162 | 23%, 0.4% | 21%, 0.8% | 19%, 0.5% | 11%, 0.3% |
| rich flight, test 160–162 | 16%, 0.3% | 20%, 0.8% | 18%, 0.7% | 11%, 0.4% |
| classic, test 140–142 | 33%, 1.2% | 42%, 2.3% | 33%, 0.9% | 26%, 0.4% |
| rich, test 140–142 | 29%, 0.4% | 41%, 0.8% | 32%, 0.5% | 24%, 0.3% |

The mission pasture sets favour model-v0.7 at 0.75 (more breaks found, no false). The flight test farms, the
independent check closest to a real flight, do not: from 0.75 it finds 19% and 18% of the breaks (model-v0.5 from
0.7: 23% and 16%) with more false frames (0.5% and 0.7%, against 0.4% and 0.3%), and from 0.8 it matches
model-v0.5's false frames with fewer breaks (11%, against 23% and 16%). The drone's
alert path can now take a broken-wire threshold of its own (`class_conf`), but no value makes model-v0.7 better
than model-v0.5 on both counts.

### The shared held-out sets (PNG)

[eval_heldout.json](eval_heldout.json), [benchmark/heldout.json](../../benchmark/heldout.json): mAP50 within −0.004
and +0.006 of model-v0.5, `wire_break` −0.011 to +0.044 (classic mission pasture), false-break frames 0.0–0.5%
(model-v0.5: 0.0–0.5%).

| Set | Frames | mAP50 v0.5 → v0.7 | `wire_break` mAP50 | `wire_break` P / R |
|---|---|---|---|---|
| classic: old validation farms | 700 | 0.928 → 0.927 | 0.850 → 0.839 | 0.88 / 0.74 → 0.92 / 0.72 |
| classic: v2 validation farms | 600 | 0.956 → 0.960 | 0.816 → 0.836 | 0.95 / 0.66 → 0.97 / 0.67 |
| **classic: test seeds 140–142** | 750 | 0.937 → 0.939 | 0.808 → 0.817 | 0.89 / 0.65 → 0.89 / 0.67 |
| classic: mission pasture | 400 | 0.976 → 0.982 | 0.865 → 0.909 | 1.00 / 0.72 → 0.94 / 0.89 |
| classic: re-fly close-ups | 400 | 0.982 → 0.985 | 0.972 → 0.970 | 0.97 / 0.89 → 0.97 / 0.87 |
| rich: validation farms | 600 | 0.952 → 0.952 | 0.849 → 0.852 | 0.90 / 0.73 → 0.93 / 0.72 |
| **rich: test seeds 140–142** | 750 | 0.937 → 0.941 | 0.783 → 0.800 | 0.89 / 0.61 → 0.92 / 0.62 |
| rich: mission pasture | 400 | 0.976 → 0.978 | 0.865 → 0.883 | 1.00 / 0.72 → 0.96 / 0.68 |
| rich: re-fly close-ups | 400 | 0.987 → 0.983 | 0.969 → 0.975 | 0.96 / 0.88 → 0.99 / 0.83 |

### Real photos: power lines (TTPLA)

TTPLA's 1,242 drone photos of power lines, where every fault box and every animal box is false
([real/ttpla.json](real/ttpla.json)).

| Frames with a false… | v0.5 from 0.7 | v0.6 from 0.7 | **v0.7 from 0.7** | v0.5 from 0.5 | v0.6 from 0.5 | **v0.7 from 0.5** |
|---|---|---|---|---|---|---|
| broken wire | 0 | 2 | **0** | 5 (0.4%) | 44 (3.5%) | **12 (1.0%)** |
| fallen post | 1 | 2 | **4** | 15 (1.2%) | 12 (1.0%) | **19 (1.5%)** |
| branch | 1 | 1 | **0** | 13 (1.0%) | 68 (5.5%) | **10 (0.8%)** |
| cow | 316 (25%) | 577 (46%) | **319 (26%)** | 1,042 (84%) | 1,069 (86%) | **1,031 (83%)** |

On real images model-v0.7 is close to model-v0.5, and well below model-v0.6's false boxes.

## Fence looks: the stress test

The same 750 flight test frames per look ([fence_looks/looks.json](fence_looks/looks.json)). None of these farms
is in the training.

| v0.5 → v0.6 → **v0.7** | mAP50 | `wire` mAP50 | Broken wires from 0.7 | Fallen posts from 0.7 | Branches from 0.7 |
|---|---|---|---|---|---|
| Classic | 0.919 → 0.928 → **0.927** | 0.993 → 0.993 → 0.993 | 22% → 26% → **22%** | 93% → 92% → **91%** | 81% → 86% → **79%** |
| Polytape, 40 mm | 0.865 → 0.883 → **0.834** | 0.966 → 0.982 → **0.778** | 4% → 8% → **5%** | 87% → 91% → **85%** | 81% → 88% → **79%** |
| Polyrope, 6 mm | 0.840 → 0.873 → **0.841** | 0.952 → 0.980 → **0.898** | 0% → 3% → **1%** | 78% → 85% → **79%** | 81% → 88% → **84%** |
| Polywire, 3 mm | 0.741 → 0.756 → **0.690** | 0.461 → 0.434 → 0.037 | 0% → 0% → 0% | 61% → 76% → **72%** | 77% → 84% → **72%** |
| Steel wire, 2.5 mm | 0.712 → 0.725 → **0.686** | 0.293 → 0.219 → 0.014 | 0% → 0% → 0% | 59% → 75% → **70%** | 77% → 79% → **72%** |

- **Fallen posts on thin wire: +11 points** (59% → 70% on steel wire, 61% → 72% on polywire), two-thirds of
  model-v0.6's gain, with half its real-conductor frames.
- **Wires on rope and tape: lost.** Trained on thin strands labelled as no wire, with no rope or tape to set against
  them, the model stops boxing thin white strands: `wire` mAP50 0.966 → 0.778 on polytape, 0.952 → 0.898 on
  polyrope. On steel wire and polywire it no longer boxes the wire at all (0.01–0.04), as its labels asked; the mAP50
  of those looks falls with it.
- Branches drop on four of the five looks (−2 to −5 points; polyrope +3). No false fallen post or branch anywhere.

## Decision

**Not adopted.** model-v0.5 stays the default everywhere, and no TensorRT engine was built.

- **Gained:** fallen posts on thin wire (+11 points), higher val mAP50 (0.957, against 0.952 on the same set), and
  far fewer false boxes on TTPLA than model-v0.6.
- **Lost:** false broken wires, the reason for this model: twice model-v0.5's false-break frames on the four test
  stream sets, 8 false frames from 0.7 in the replay (1), and the same false alert at the corner as model-v0.6.
  Also wires on rope and tape, and a few points of branches.

## What it teaches, and next

- **Negatives from new farms did not reach the corner that fails.** 2,000 frames near corners with no break did not
  lower the confidence at the mission's corner (6 frames from 0.7, against model-v0.6's 5). The corners the
  generator draws may not line their strands up the way that one does, or 2,000 frames among 13,100 are too few.
- **Both fine-tunes from model-v0.5 made broken wires surer.** What model-v0.6 and model-v0.7 share is the
  steel-wire and polywire frames and 8 more epochs on model-v0.5's mix, and both raise false breaks. A control run,
  model-v0.5 fine-tuned 8 epochs on its own mix with nothing added, would tell whether the extra training alone does
  it or the thin-wire frames; until then no added data can be credited or blamed for the false breaks.
- **No wire boxes on thin wire needs the thick conductors beside it.** model-v0.6, which had rope and tape too, kept
  its wires; model-v0.7 lost them. A later mix that keeps the steel-wire and polywire frames should keep rope and
  tape as well.

## Files

| File | Content |
|---|---|
| [args.yaml](args.yaml) | Ultralytics arguments (as saved by the last resumed session) |
| [results.csv](results.csv) | Losses and validation metrics per epoch |
| [data.yaml](data.yaml) | The training mix (`tools/mix_dataset.py` command) |
| [eval_stream.json](eval_stream.json) | `tools/eval_sets.py`: the 8 stream sets, model-v0.5 and model-v0.7 |
| [eval_heldout.json](eval_heldout.json) | `tools/eval_sets.py`: the 9 shared held-out sets, model-v0.7 |
| [wb_thresholds.json](wb_thresholds.json) | Broken wires found and false-break frames at conf 0.7, 0.75 and 0.8 on the 6 JPEG stream sets, both models |
| [mission_replay.json](mission_replay.json) | `tools/eval_mission.py` on the recorded classic mission, model-v0.7 (and model-v0.5 as recorded before), broken wires from 0.75, and each model's boxes at the corner of the false alert |
| [fence_looks/looks.json](fence_looks/looks.json) | The fence-look stress test, model-v0.7 |
| [real/ttpla.json](real/ttpla.json) | `tools/ttpla_check.py` on the 1,242 TTPLA photos, model-v0.7 |
