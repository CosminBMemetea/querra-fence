# Fence detector: models and data

Every fence detector model has a record here: the data it was trained on, the code that made that data, how it was
trained, how it scored offline and in live flights, and why it is or is not used. The story behind each version is in
[docs/retraining-log.md](../docs/retraining-log.md). Intended use and limits are in the
[model card](../docs/model-card.md).

| File | What it holds |
|---|---|
| [models.json](models.json) | **Model registry.** One entry per model: status, data, code commit, training, scores, live results, sha256 of every file |
| [datasets.json](datasets.json) | **Dataset registry.** Generator command and commit, look, seeds, splits and the role of each split (train / val / test) |
| [runs/](runs) | **Run records** from model-v0.4 on: training arguments, scores per epoch, data mix, held-out scores, live flights, engine build |
| [tools/model_registry.py](../tools/model_registry.py) | Validates both registries, writes the table below, checks local files against the hashes |

## Models

<!-- registry:start -->
| Model | Status | Date | Trained on | Test mAP50 classic / rich | `wire_break` recall classic / rich | Live classic: faults, false alerts | Live rich | Run |
|---|---|---|---|---|---|---|---|---|
| **model-v0.4** | live-sim | 2026-11-20 | 7,200 frames, 4 datasets | 0.938 / 0.938 | 0.69 / 0.68 | 3 of 3, 13 | 3 of 3, 6 | [model-v0.4](runs/model-v0.4) |
| **model-v0.3** | default | 2026-11-19 | 4,800 frames, 2 datasets | 0.911 / 0.71 | 0.61 / 0.14 | 3 of 3, 5 | 1 of 3, 0 | – |
| **model-v0.2** | retired | 2026-11-19 | 3,500 frames, 1 dataset | 0.897 / – | 0.42 / – | 3 of 3, 385 false frames | – | – |
| **model-v0.1** | retired | 2026-11-19 | 3,500 frames, 1 dataset | – / – | – / – | 2 of 3 (60 s flight, F3 not reached), 72 false frames | – | – |
<!-- registry:end -->

- **Test:** the held-out farms with seeds 140–142 in each world look. These farms are never used for training or for
  picking an epoch.
- **Live:** one inspection flight over the mission pasture. Gazebo streams the camera to the Jetson, which runs the
  TensorRT engine with 5-of-8 GPS confirmation (conf ≥ 0.7) and places alerts with PX4's own pose. An alert is a real
  fault when its class matches one of F1–F3 within 15 m.
- **Statuses:**
  - `default`: what the system uses unless told otherwise (the ROS 2 detector, the replay demo, field mode).
  - `live-sim`: used for live Gazebo flights (`ros.sh demo tcp://…`).
  - `retired`: kept for comparison.

## How a model is made

1. **Data.** `tools/make_dataset.sh` renders random farms in Gazebo and writes YOLO labels from the 3D ground truth.
   Each new dataset gets an entry in `datasets.json` with its command and the commit of the generator. Test splits are
   marked `"role": "test"`. The validator refuses a model that trains or validates on one of them.
2. **Mix.** `tools/mix_dataset.py` writes the training mix as lists of images, so nothing is copied. Old data stays in
   the mix so the model keeps what it learned.
3. **Train.** `tools/train_yolo.py --data … --model <parent>.pt --name fence-yolo11n-vX.Y`. `--resume` continues a
   paused run. The output is `best.pt` and `best.onnx` (416×640).
4. **Score offline.** `tools/eval_sets.py <parent>.pt <new>.pt --json …` scores both models on the held-out sets of
   both looks. `tools/eval_mission.py` replays the recorded mission flight through each model.
5. **Build the engine on the Jetson.**
   `trtexec --onnx=… --saveEngine=fence-yolo11n-vX.Y-fp16.engine --fp16` in `~/querra-scout-20261107/models/fence-yolo`.
6. **Fly it.** Run the live chain in both looks with
   `./ros.sh demo tcp://MAC:5601 px4:=true refly:=true engine:=/models/<engine>`.
   Offline scores alone are not enough: model-v0.4 scored better offline and still raised more false alerts on the
   classic mission.
7. **Record and decide.** Copy the run record to `runs/model-vX.Y/`. Add the model to `models.json` with its hashes
   (`shasum -a 256`) and a status. Run `python3 tools/model_registry.py --write`, update the retraining log and the
   model card, and attach `.pt`, `.onnx` and `classes.json` to the GitHub release `model-vX.Y`.

```bash
python3 tools/model_registry.py                          # validate and print the table
python3 tools/model_registry.py --write                  # rewrite the table above
python3 tools/model_registry.py --check ~/querra-data/models   # sha256 of local model files against the registry
```

## Where the files are

| What | Where |
|---|---|
| Weights (`.pt`, `.onnx`) | GitHub release `model-vX.Y`; training machine `~/querra-data/models` |
| TensorRT engines | Jetson `~/querra-scout-20261107/models/fence-yolo` (mounted as `/models` in the ROS 2 container). Engines are built per device and are not released |
| Datasets | Training machine `~/querra-data/<dataset id>` (0.1–1.7 GB each); rebuilt from `datasets.json` |
| Runs | `runs/` here (small text files); the full Ultralytics output stays in `~/querra-data/train/` |
