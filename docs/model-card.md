# Model card: Querra fence detector (YOLO11n)

| | |
|---|---|
| Task | Object detection on the drone's inspection camera (640×400, tilted 55° down, about 12 m above ground) |
| Classes | `post`, `wire`, `wire_break`, `fallen_post`, `branch`, `cow`, `sheep` |
| Architecture | Ultralytics YOLO11n (2.6 M parameters), fine-tuned from the COCO `yolo11n.pt` |
| Input | ONNX/TensorRT: 1×3×416×640 RGB, values 0–1, frame letterboxed (padding value 114) |
| Output | 1×11×5460 (Ultralytics layout: cx, cy, w, h and 7 class scores); class-aware NMS on the host |
| Target hardware | Jetson Orin Nano Super 8 GB, JetPack R36.4.4, TensorRT 10.3, FP16 engine built with `trtexec` |
| Releases | `model-v0.1` (preliminary), `model-v0.2`, `model-v0.3` (current); history in [retraining-log.md](retraining-log.md) |

## Training data

Everything is synthetic. `tools/make_dataset.py` builds random farms with the same generator as the simulation
(`sim/gen_world.py`), renders them in Gazebo Harmonic with a copy of the drone camera, and computes every box from the
known 3D geometry of posts, wires, faults and animals. Nobody labelled anything by hand.

- v0.1 / v0.2: 4,200 frames from 12 farms (10 training, 2 held-out validation).
- v0.3: fine-tuned on 4,800 frames: 2,400 new frames from 8 farms full of broken and dead strands, plus 2,400 v0.2
  training frames. Tested on 3 new farm seeds (750 frames) never used for training.
- Known label limits:
  - Boxes ignore occlusion; a post hidden under a tree canopy still has its box.
  - `wire` boxes are the bounding box of a whole 5–7 m span, so they are large and diagonal.

## Intended use

- Research prototype for the inspection drone and the Jetson pipeline.
- Produces candidate faults for a person to check, together with the GPS position.
- **Not validated on real fences or real animals.**

## Known limitations

- **Simulation only.** Gazebo grass, box-shaped animals and perfect cylinders are not real images. Expect a large
  drop on real footage until the model is fine-tuned on photos from the field. The field recorder on the Jetson saves
  raw frames for exactly that.
- **False `wire_break`.** A dead strand next to a live one looks like a missing wire. v0.2 gave 385 false frames in a
  simulated mission on the Jetson. v0.3 cuts false frames by 15–37%. With multi-frame GPS confirmation
  (`tools/confirm.py`, 5 of 8 frames, conf ≥ 0.7) false alerts drop from 33 to 6 with all faults still found. Use
  confirmed alerts, not single frames.
- **Indoors and other scenes.** Out-of-domain images produce confident false animals; a person indoors came out as `cow`.
- **Thin wires.** At 12 m the wire is about 1 px wide. Detection relies on the post-to-post pattern more than the wire itself.
- **Trained on the "classic" look only.** On the new "rich" world (textured grass, hills; 2026-11-20) the same live
  chain found **1 of 3** real faults (the branch, 4.0 m away) and no false alert, against 3 of 3 with 5 false alerts
  on the classic world. That is a domain gap inside the simulation itself. Use `./start.sh --look classic` for live
  detector tests until a model is trained on both looks (v0.4).

## Metrics

| mAP50 | v0.2 | v0.3 |
|---|---|---|
| Old validation farms (700 frames) | 0.921 | 0.916 |
| v2 validation farms (600) | 0.913 | 0.932 |
| **Held-out test, new seeds (750)** | 0.897 | **0.912** |
| `wire_break` on the held-out test | 0.577 | **0.684** |

v0.2 per class (old validation): post 0.968, wire 0.977, wire_break 0.818, fallen_post 0.916, branch 0.934, cow 0.915,
sheep 0.922. Jetson end to end: 13.3 fps; detector 20.8 ms per frame (p50), of which 4.7 ms is GPU inference.

## Reproduce

```bash
./stop.sh                                    # dataset generation needs its own Gazebo
tools/make_dataset.sh --layouts 12 --val-layouts 2 --frames 350     # ~8 min on an M2, ~100 MB
python tools/train_yolo.py --epochs 25 --device cpu                 # or mps; writes best.pt + best.onnx (416×640)
/usr/src/tensorrt/bin/trtexec --onnx=best.onnx --saveEngine=fence-yolo11n-fp16.engine --fp16   # on the Jetson
```
