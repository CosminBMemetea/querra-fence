# model-v0.8 · control run: more training, no new data (not adopted)

| | |
|---|---|
| Status | **not adopted**: model-v0.5 stays the default. A control run, kept for comparison |
| Date | 2026-11-28 |
| Parent | model-v0.5 (fine-tuned) |
| Code | `85f3ebb` (training and eval scripts as for model-v0.7) |
| Files | `fence-yolo11n-v0.8.pt`, `.onnx` (416×640); no Jetson engine; sha256 in [models.json](../../models.json) |

## Why

[model-v0.6](../model-v0.6) and [model-v0.7](../model-v0.7) added different data to model-v0.5 and both raised false
broken wires. What they shared was the 1,500 steel-wire and polywire frames, and 8 more epochs on top of model-v0.5.
This run keeps the epochs and drops the data: model-v0.5 fine-tuned 8 epochs on **its own mix**, nothing added, with
the same settings. If its false breaks rise too, the extra training raised them; if not, the added data did.

## Data and training

- **Data:** model-v0.5's training mix unchanged, 9,600 frames of 6 datasets ([data.yaml](data.yaml),
  [its data](../model-v0.5#data)); validation is model-v0.5's 1,800 frames. No new dataset.
- **Training:** as model-v0.6 and model-v0.7: YOLO11n from model-v0.5, 8 epochs at 640 px, batch 8, M2 GPU (MPS),
  AdamW lr 0.000909, 3 warm-up epochs, mosaic off for the last 3, 15-minute cooling breaks. **1.2 h of training**, 2.2 h
  with the breaks ([args.yaml](args.yaml), [results.csv](results.csv)).

| Epoch | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|
| 1 | 0.942 | 0.768 | 0.943 | 0.892 |
| 2 | 0.938 | 0.751 | 0.929 | 0.893 |
| 3 | 0.936 | 0.757 | 0.936 | 0.885 |
| 4 | 0.937 | 0.759 | 0.935 | 0.888 |
| 5 | 0.948 | 0.772 | 0.952 | 0.895 |
| 6 | 0.947 | 0.771 | 0.947 | 0.899 |
| **7** | **0.950** | **0.792** | 0.952 | 0.901 |
| 8 | 0.955 | 0.792 | 0.956 | 0.915 |

Ultralytics keeps the epoch with the best mAP50-95: epoch 7 (0.79184, against 0.79180) is the model. Final
per-class mAP50: post 0.990, wire 0.992, `wire_break` 0.793 (precision 0.89, recall 0.64; model-v0.5: 0.801, 0.91,
0.66), `fallen_post` 0.988, `branch` 0.960, cow 0.957, sheep 0.967. All classes 0.950 (model-v0.5: 0.952).

## The answer: the extra training did not raise false breaks

### Stream sets

The 8 sets posed like the flight and compressed like the stream ([eval_stream.json](eval_stream.json),
[benchmark/stream.json](../../benchmark/stream.json)). `wb_false` for model-v0.6 and model-v0.7 for reference.

| Set | mAP50 v0.5 → **v0.8** | `wire_break` P / R | `wb_false` v0.5 → **v0.8** | v0.6 | v0.7 |
|---|---|---|---|---|---|
| classic flight, mission pasture, JPEG | 0.963 → 0.964 | 1.00 / 0.69 → 0.98 / 0.71 | 0.0% → 0.0% | 0.2% | 0.0% |
| rich flight, mission pasture, JPEG | 0.954 → 0.949 | 0.93 / 0.71 → 0.81 / 0.71 | 0.0% → 0.0% | 0.5% | 0.2% |
| classic flight, test seeds 160–162, JPEG | 0.926 → 0.920 | 0.71 / 0.58 → 0.66 / 0.50 | 0.4% → **0.1%** | 1.1% | 0.8% |
| rich flight, test seeds 160–162, JPEG | 0.914 → 0.921 | 0.73 / 0.33 → 0.70 / 0.36 | 0.3% → **0.1%** | 1.2% | 0.8% |
| classic, test seeds 140–142, JPEG | 0.910 → 0.915 | 0.76 / 0.54 → 0.79 / 0.58 | 1.2% → **0.4%** | 1.3% | 2.3% |
| rich, test seeds 140–142, JPEG | 0.920 → 0.921 | 0.80 / 0.52 → 0.82 / 0.55 | 0.4% → 0.5% | 0.5% | 0.8% |
| classic flight, mission pasture, PNG | 0.974 → 0.976 | 1.00 / 0.68 → 1.00 / 0.71 | 0.0% → 0.0% | 0.0% | 0.0% |
| rich flight, mission pasture, PNG | 0.969 → 0.965 | 1.00 / 0.78 → 0.98 / 0.79 | 0.0% → 0.0% | 0.2% | 0.0% |

### The mission replay

The recorded classic mission, 5 of 8 frames from conf 0.7, refined alert positions
([mission_replay.json](mission_replay.json)).

| | model-v0.5 | model-v0.7 | **model-v0.8** |
|---|---|---|---|
| F1 broken wire: frames that saw it (of 249), best conf | 66, 0.87 | 65, 0.91 | 66, 0.87 |
| False `wire_break` frames, conf ≥ 0.5 / ≥ 0.7 | 9 / 1 | 24 / 8 | **4 / 1** |
| Frames with a break box at the corner (57 m from F1), from 0.5 / 0.7 | 5 / 1 | 7 / 6 | **0 / 0** |
| Confirmed alerts | 3: 3 faults + 0 false | 4: 3 faults + 1 false | **3: 3 faults + 0 false** (0.5, 0.5, 1.4 m) |

**So the extra epochs are not what raised model-v0.6's and model-v0.7's false breaks; the data they added did.** The
steel-wire and polywire frames are in both and are the first suspect. model-v0.6's rope and tape breaks and
model-v0.7's corner farms may add to it; only a run with one of them at a time can tell.

### But it is not a better model: quieter, not sharper

The control lowered the confidence of broken wires in general, true ones too. From 0.7 it finds fewer of the breaks
on the flight test farms (IoU 0.3, [wb_thresholds.json](wb_thresholds.json)):

| Set | model-v0.5 from 0.7 | from 0.75 | **model-v0.8 from 0.7** | from 0.75 |
|---|---|---|---|---|
| classic flight, mission pasture | 67%, 0.0% | 46%, 0.0% | **71%, 0.0%** | 67%, 0.0% |
| rich flight, mission pasture | 50%, 0.0% | 33%, 0.0% | **54%, 0.0%** | 54%, 0.0% |
| classic flight, test 160–162 | 23%, 0.4% | 15%, 0.0% | **9%, 0.1%** | 7%, 0.0% |
| rich flight, test 160–162 | 16%, 0.3% | 12%, 0.1% | **9%, 0.1%** | 6%, 0.0% |
| classic, test 140–142 | 33%, 1.2% | 25%, 0.4% | **29%, 0.4%** | 24%, 0.1% |
| rich, test 140–142 | 29%, 0.4% | 21%, 0.1% | **27%, 0.5%** | 20%, 0.3% |

At the same false-break rate, model-v0.5 from 0.75 finds more breaks than model-v0.8 from 0.7 on the flight test
farms (15% and 12%, against 9% and 9%). On the farms of seeds 140–142 the control is ahead on the classic look (29%
against 25%, both 0.4% false) and behind on the rich one. It moved along model-v0.5's trade-off rather than past it.

### Repeating the same data overfits

model-v0.5 had already seen these 9,600 frames for 6 epochs; 8 more cost it elsewhere:

- **Held-out sets (PNG)** ([eval_heldout.json](eval_heldout.json)): mAP50 equal or lower on all 9 (down to −0.005),
  `wire_break` mAP50 lower on all 9 (−0.003 to −0.034).
- **Fence looks** ([fence_looks/looks.json](fence_looks/looks.json)): broken wires from 0.7 on the classic look 22% →
  11% (from 0.5: 39% → 37%), fallen posts from 0.7 on steel wire 59% → 49%, polywire 61% → 55%, classic 93% → 89%.
- **Real photos (TTPLA, 1,242 drone photos of power lines,** [real/ttpla.json](real/ttpla.json)**):** false branches in
  242 photos from 0.5 (19.5%; model-v0.5: 13, 1.0%) and 15 from 0.7 (1), false cows from 0.7 in 36% (25%). Broken
  wires: 8 from 0.5 (5), 2 from 0.7 (0).

model-v0.7, trained as long but with 3,500 new frames, kept TTPLA close to model-v0.5 (10 false branches from 0.5):
new data held back the overfitting that the same data alone brought.

## Decision

**Not adopted.** model-v0.5 stays the default. The control answers its question and is not a better model: fewer
false breaks because it is less sure of every break, fewer breaks found on the flight test farms, lower on every
held-out set, and many more false branches and cows on real photos.

## What it teaches, and next

- **The added data raised the false breaks, not the training length.** First suspect: the steel-wire and polywire
  frames with no wire boxes, in both model-v0.6 and model-v0.7. The direct test is model-v0.5's mix plus only those
  1,500 frames.
- **Compare at the same false-break rate.** A model that is less sure of breaks looks better at a fixed 0.7 and
  worse at recall; the threshold that gives each model model-v0.5's false-break rate on validation, then the breaks
  found, is the fair comparison. The drone's alert path takes a broken-wire threshold of its own (`class_conf`).
- **Don't fine-tune on the same frames again.** 8 more epochs on model-v0.5's data made it worse on real photos.
  Later runs should bring new data, or train fewer epochs, and keep TTPLA as a guard.

## Files

| File | Content |
|---|---|
| [args.yaml](args.yaml) | Ultralytics arguments (as saved by the last resumed session) |
| [results.csv](results.csv) | Losses and validation metrics per epoch |
| [data.yaml](data.yaml) | model-v0.5's training mix, reused unchanged |
| [eval_stream.json](eval_stream.json) | `tools/eval_sets.py`: the 8 stream sets, model-v0.5 and model-v0.8 |
| [eval_heldout.json](eval_heldout.json) | `tools/eval_sets.py`: the 9 shared held-out sets, model-v0.8 |
| [wb_thresholds.json](wb_thresholds.json) | Broken wires found and false-break frames at conf 0.7, 0.75 and 0.8 on the 6 JPEG stream sets, both models |
| [mission_replay.json](mission_replay.json) | `tools/eval_mission.py` on the recorded classic mission, model-v0.8 (and model-v0.5 as recorded before), and the boxes at the corner of model-v0.6's and model-v0.7's false alert |
| [fence_looks/looks.json](fence_looks/looks.json) | The fence-look stress test, model-v0.8 |
| [real/ttpla.json](real/ttpla.json) | `tools/ttpla_check.py` on the 1,242 TTPLA photos, model-v0.8 |
