# Tests

```bash
~/.querra-train-venv/bin/python -m pytest -q          # on the Mac, about 15 s
```

They run on every push too (`.github/workflows/checks.yml`), with the registry, release-notes and README checks.
Nothing here needs a GPU, Gazebo, a model or ROS 2: `conftest.py` stands in for ROS 2 where it is not installed, so
the ground robot's nodes are tested on the Mac.

| File | What it guards |
|---|---|
| `test_confirm.py` | the drone's alert confirmation: where a box lands on the ground, 5 of 8 frames; the Jetson's copy has the same logic |
| `test_ugv_alerts.py` | the ground robot's alerts: 5 of 8 steps of 0.5 m, fallen posts from their own threshold, where a box lands on the fence |
| `test_video_eval.py` | DJI subtitles, the drone's course from them, confirming by frames |
| `test_ugv_eval.py` | scoring a patrol from the relay's log, end to end |
| `test_label_drafts.py` | the labelling server: what it writes, what it refuses |
| `test_train_with_breaks.py` | the cooling breaks, also when training is started detached |
| `test_registry.py` | the model registry is valid, and its checks catch two defaults, a test split in training, a bad hash |

Each was checked against a real bug of this project put back in: a renamed loop variable in `ugv_eval.py`, the
Jetson's `confirm.py` drifting, the labelling server without its Host check, the alert node's step boundary, and
`train_with_breaks.py` before its SIGINT fix. Every one fails its test.
