# model-v0.9 · steel-wire and polywire frames only (not adopted)

| | |
|---|---|
| Status | **not adopted**: model-v0.5 stays the default |
| Date | 2026-11-28 |
| Parent | model-v0.5 (fine-tuned) |
| Code | `d431dba` (training and eval scripts as for model-v0.8) |
| Files | `fence-yolo11n-v0.9.pt`, `.onnx` (416×640); no Jetson engine; sha256 in [models.json](../../models.json) |

## Why

The control run [model-v0.8](../model-v0.8) showed that 8 more epochs on model-v0.5's data did not raise false
broken wires, so the data [model-v0.6](../model-v0.6) and [model-v0.7](../model-v0.7) added did. Both added the
1,500 steel-wire and polywire frames. This run adds **only those frames** to model-v0.5's mix and trains exactly like
the control, so the two differ by those frames alone.

## Data and training

- **Data:** model-v0.5's 9,600 training frames plus the 6 steel-wire and polywire layouts of
  `drone_yolo_looks_stream` (L250, L251, L254, L255, L258, L259; 250 frames each). These farms are drawn with real
  conductors (2.5 mm grey steel wire, 3 mm yellow polywire) and have **no wire or `wire_break` boxes**: from 11 m the
  wire is a tenth of a pixel. 11,100 frames, 7,244 of them JPEG ([data.yaml](data.yaml)); validation is model-v0.5's
  1,800 frames.
- **Training:** as the control: YOLO11n from model-v0.5, 8 epochs at 640 px, batch 8, M2 GPU (MPS), AdamW lr
  0.000909, 3 warm-up epochs, mosaic off for the last 3, 15-minute cooling breaks. **1.4 h of training**, 2.7 h with
  the breaks and 17 minutes of the Mac asleep during one break ([args.yaml](args.yaml), [results.csv](results.csv)).

| Epoch | mAP50 | mAP50-95 | Precision | Recall |
|---|---|---|---|---|
| 1 | 0.943 | 0.774 | 0.944 | 0.891 |
| 2 | 0.928 | 0.751 | 0.919 | 0.877 |
| 3 | 0.934 | 0.756 | 0.939 | 0.882 |
| 4 | 0.939 | 0.759 | 0.933 | 0.893 |
| 5 | 0.929 | 0.757 | 0.940 | 0.879 |
| 6 | 0.948 | 0.778 | 0.951 | 0.897 |
| 7 | 0.951 | 0.792 | 0.948 | 0.901 |
| **8** | **0.954** | **0.799** | 0.963 | 0.902 |

Epoch 8 is the model. Final per-class mAP50: post 0.992, wire 0.993, `wire_break` 0.815 (precision 0.95, recall
0.64; model-v0.5: 0.801, 0.91, 0.66), `fallen_post` 0.983, `branch` 0.975, cow 0.956, sheep 0.966. All classes 0.954
(model-v0.5: 0.952).

## The answer: these frames raise the false breaks

### Stream sets

The 8 sets posed like the flight and compressed like the stream ([eval_stream.json](eval_stream.json),
[benchmark/stream.json](../../benchmark/stream.json)). `wb_false` is the share of frames with a false `wire_break`
box from 0.7; the control and model-v0.7 for reference.

| Set | mAP50 v0.5 → **v0.9** | `wire_break` P / R | `wb_false` v0.5 → **v0.9** | control v0.8 | v0.7 |
|---|---|---|---|---|---|
| classic flight, mission pasture, JPEG | 0.963 → 0.963 | 1.00 / 0.69 → 0.98 / 0.71 | 0.0% → 0.0% | 0.0% | 0.0% |
| rich flight, mission pasture, JPEG | 0.954 → 0.957 | 0.93 / 0.71 → 0.90 / 0.75 | 0.0% → 0.2% | 0.0% | 0.2% |
| classic flight, test seeds 160–162, JPEG | 0.926 → 0.930 | 0.71 / 0.58 → 0.69 / 0.56 | 0.4% → **0.8%** | 0.1% | 0.8% |
| rich flight, test seeds 160–162, JPEG | 0.914 → 0.933 | 0.73 / 0.33 → 0.76 / 0.41 | 0.3% → 0.4% | 0.1% | 0.8% |
| classic, test seeds 140–142, JPEG | 0.910 → 0.916 | 0.76 / 0.54 → 0.81 / 0.56 | 1.2% → **1.6%** | 0.4% | 2.3% |
| rich, test seeds 140–142, JPEG | 0.920 → 0.930 | 0.80 / 0.52 → 0.88 / 0.59 | 0.4% → 0.4% | 0.5% | 0.8% |
| classic flight, mission pasture, PNG | 0.974 → 0.971 | 1.00 / 0.68 → 0.99 / 0.71 | 0.0% → 0.0% | 0.0% | 0.0% |
| rich flight, mission pasture, PNG | 0.969 → 0.968 | 1.00 / 0.78 → 0.97 / 0.75 | 0.0% → 0.0% | 0.0% | 0.0% |

### The mission replay

The recorded classic mission, 5 of 8 frames from conf 0.7, refined alert positions
([mission_replay.json](mission_replay.json)).

| | model-v0.5 | control v0.8 | model-v0.7 | **model-v0.9** |
|---|---|---|---|---|
| F1 broken wire: frames that saw it (of 249), best conf | 66, 0.87 | 66, 0.87 | 65, 0.91 | 68, 0.90 |
| False `wire_break` frames, conf ≥ 0.5 / ≥ 0.7 | 9 / 1 | 4 / 1 | 24 / 8 | **23 / 5** |
| Frames with a break box at the corner (57 m from F1), from 0.5 / 0.7 | 5 / 1 | 0 / 0 | 7 / 6 | **6 / 2** |
| Confirmed alerts | 3: 3 faults + 0 false | 3: 3 faults + 0 false | 4: 3 faults + 1 false | **3: 3 faults + 0 false** (0.4, 0.5, 1.4 m) |

At the drone's settings the replay is clean, but only just. The corner is back: 2 frames from 0.7, where an alert
needs 5, and counting every box from 0.5 the corner alert returns.

**So the steel-wire and polywire frames raise the false breaks.** Against the control, which differs by those frames
alone: false-break frames from 0.7 rose on 3 of the 4 test stream sets (0.1–0.5% to 0.4–1.6%), fivefold in the replay
(1 to 5; from 0.5, 4 to 23), and break boxes came back at model-v0.7's corner.

### But it is also more sure of true breaks

The frames moved broken-wire confidence up, true and false alike. Compared at the same false-break rate (IoU 0.3,
[wb_thresholds.json](wb_thresholds.json)), breaks found and false-break frames:

| Set | v0.5 from 0.7 | v0.5 from 0.75 | control from 0.7 | **v0.9 from 0.7** | **from 0.75** | **from 0.8** |
|---|---|---|---|---|---|---|
| classic flight, mission pasture | 67%, 0.0% | 46%, 0.0% | 71%, 0.0% | 71%, 0.0% | 67%, 0.0% | 54%, 0.0% |
| rich flight, mission pasture | 50%, 0.0% | 33%, 0.0% | 54%, 0.0% | 67%, 0.2% | 58%, 0.0% | 46%, 0.0% |
| classic flight, test 160–162 | 23%, 0.4% | 15%, 0.0% | 9%, 0.1% | 23%, 0.8% | 15%, 0.4% | 8%, 0.1% |
| rich flight, test 160–162 | 16%, 0.3% | 12%, 0.1% | 9%, 0.1% | 20%, 0.4% | 13%, 0.1% | 10%, 0.0% |
| classic, test 140–142 | 33%, 1.2% | 25%, 0.4% | 29%, 0.4% | 38%, 1.6% | 30%, 0.7% | 19%, 0.3% |
| rich, test 140–142 | 29%, 0.4% | 21%, 0.1% | 27%, 0.5% | 34%, 0.4% | 25%, 0.1% | 16%, 0.1% |

At matched false-break rates model-v0.9 finds more breaks than model-v0.5 on both mission pastures and the rich test
farms of seeds 140–142, about as many on the rich flight test farms, slightly fewer at low false rates and slightly
more at high ones on the classic farms of seeds 140–142, and fewer on the **classic flight test farms** (15% against 23%, both 0.4% false). That set is the look and pose closest
to the recorded mission. It is a different trade-off, not a clearly better one.

### Held-out sets (PNG)

[eval_heldout.json](eval_heldout.json): mAP50 higher on 5 of the 9 sets, equal on 1 and lower on 3 (−0.005 to
+0.008). `wire_break` mAP50 is higher on 8 of the 9 (−0.011 to +0.055): recall on the classic mission pasture rose
from 0.72 to 0.87. Unlike the control, no sign of overfitting.

### Fence looks: the best on fallen posts, and lost rope and tape wires

The fence-look stress test ([fence_looks/looks.json](fence_looks/looks.json)), recall from 0.7:

| | model-v0.5 | control v0.8 | model-v0.7 | **model-v0.9** |
|---|---|---|---|---|
| Fallen posts found, steel wire / polywire | 59% / 61% | 48% / 55% | 70% / 72% | **81% / 82%** |
| Fallen posts found, classic / polyrope / polytape | 93% / 78% / 87% | 89% / 77% / 85% | 91% / 79% / 85% | **95% / 89% / 92%** |
| `wire` mAP50, polyrope / polytape | 0.952 / 0.966 | 0.956 / 0.969 | 0.898 / 0.778 | **0.881 / 0.747** |
| False `wire_break` frames, polyrope / polytape | 0.0% / 0.1% | 0.0% / 0.0% | 0.1% / 0.3% | **0.4% / 0.7%** |
| Broken wires found, classic | 22% | 11% | 22% | 21% |

The thin-wire frames do what they were added for: fallen posts on steel wire and polywire are found far more often
than by any earlier model, and on every other look too. But the model loses rope and tape wires as model-v0.7 did, and
sees broken wires on those fences. model-v0.6, which also had rope and tape frames with their wires boxed, kept the
wires (0.980 and 0.982). The steel wire and polywire themselves are no longer boxed (`wire` mAP50 0.010 and 0.033,
model-v0.5 0.293 and 0.461), as the labels asked.

### Real photos

TTPLA, 1,242 drone photos of power lines ([real/ttpla.json](real/ttpla.json)): false broken wires in 17 photos from
0.5 (model-v0.5: 5) and none from 0.7 (0); false branches in 15 from 0.5 (13), so no sign of the control's 242; false
cows from 0.7 in 33% (25%; control 36%).

## Decision

**Not adopted.** model-v0.5 stays the default. The run answers its question: the steel-wire and polywire frames are
the cause of model-v0.6's and model-v0.7's false broken wires. The model is not ready to replace model-v0.5. In the
replay it has five times model-v0.5's false-break frames from 0.7, and the corner boxes are back. At matched rates it
finds fewer breaks on the flight test look closest to the mission. It loses rope and tape wires. And it has not flown.

## What it teaches, and next

- **The cause is found: these 1,500 frames.** They also bring the largest gain yet on fallen posts on thin wire, so
  they are worth keeping if the side effect can go. The first suspect is how they are labelled.
- **Likely mechanism (not yet tested):** the strands are drawn at their real size and rendered at 3× and averaged, so
  a thin wire still shows as a faint line, most of all yellow polywire near the camera. With no box there, the model
  learns that a faint wire is not a wire. On rope, tape and distant classic wire it then drops stretches of wire, and
  a wire that stops looks like a break.
- **Next, one change against this run:** the same frames, with the thin wire boxed where it is visible in the image
  and left out where it is not. If false breaks fall back to the control's level and the fallen-post gain stays, that
  is the mix to fly.
- **Compare at the same false-break rate, and keep TTPLA as the guard.** Both caught what a fixed 0.7 would have hidden.

## Files

| File | Content |
|---|---|
| [args.yaml](args.yaml) | Ultralytics arguments (as saved by the last resumed session) |
| [results.csv](results.csv) | Losses and validation metrics per epoch |
| [data.yaml](data.yaml) | The training mix: model-v0.5's plus the steel-wire and polywire layouts |
| [eval_stream.json](eval_stream.json) | `tools/eval_sets.py`: the 8 stream sets, model-v0.5 and model-v0.9 |
| [eval_heldout.json](eval_heldout.json) | `tools/eval_sets.py`: the 9 shared held-out sets, model-v0.9 |
| [wb_thresholds.json](wb_thresholds.json) | Broken wires found and false-break frames at conf 0.7, 0.75 and 0.8 on the 6 JPEG stream sets, both models |
| [mission_replay.json](mission_replay.json) | `tools/eval_mission.py` on the recorded classic mission, model-v0.9 (and model-v0.5 as recorded before), and the boxes at the corner of model-v0.6's and model-v0.7's false alert |
| [fence_looks/looks.json](fence_looks/looks.json) | The fence-look stress test, model-v0.9 |
| [real/ttpla.json](real/ttpla.json) | `tools/ttpla_check.py` on the 1,242 TTPLA photos, model-v0.9 |
