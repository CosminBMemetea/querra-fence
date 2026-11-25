# Real fence video · DJI Mini 4 Pro

Every model so far was trained and scored in simulation. A video of a real fence, filmed from the view the drone
models learned, is the first test of how they do in the real world. `tools/video_eval.py` runs a model over the
video with the Jetson's alert rule and shows what it would have raised.

## The flight

Film the way the simulated drone flies, so that model-v0.5 sees what it was trained on:

| | Setting | The simulated drone |
|---|---|---|
| Video | 4K, 30 fps, 16:9, normal colour (not D-Log M) | 640×400, 15 fps |
| Height | 12 m above the take-off point | 11–13 m |
| Gimbal | 55° down | 52–58° down |
| Position | 2–3 m beside the fence, flying along it, camera ahead | 1.5–3.5 m beside |
| Speed | about 3 m/s | 3–4 m/s |

- In DJI Fly, turn on **Video Subtitles** (camera settings). The drone then writes a `.SRT` next to each video,
  with its GPS position and height for every frame. With it, alerts get a position on the map and the sightings
  must agree on a spot on the ground, as in flight. Without it the tool still works, by frames only.
- Fly forward with the camera ahead, not sideways: the SRT has no heading, so the tool takes the direction of travel.
- A second pass at 6 m with the gimbal at 55° matches the drone's close look before it raises an alert.
- Save the route as a waypoint flight, so later flights repeat it.
- A fault to find helps: a wire unclipped and hanging, a branch laid across the wires. Note where it is.
- Before flying: register as an operator (EU: the Mini 4 Pro with its standard battery is class C0, but it has a
  camera) and check the local zone map.

## Run the model over it

Copy the `.MP4` and its `.SRT` from the drone's card to the Mac, into the same folder, then:

```bash
~/.querra-train-venv/bin/python tools/video_eval.py ~/Movies/DJI_20261125120000_0001_D.MP4 --pitch 55
```

It decodes the video at 15 fps and 1280 px wide (like the field camera on the Jetson), runs the detector, and
confirms an alert when the same fault class (conf ≥ 0.7) shows in 5 of the last 8 frames within 5 m on the ground.
Results go to `run/video/<video name>/`:

- `annotated.mp4`: every box; fault boxes that count toward an alert are thick, and each alert shows for 2 s
- `alerts.json`: time, class, confidence and, with the SRT, the position and a map link
- `alerts/`: the frame that confirmed each alert
- `detections.jsonl`: every box in every frame, for scoring later

Options: `--model` (default model-v0.5), `--start`/`--end` (seconds), `--pitch` (the gimbal angle you flew with),
`--hfov` (69.7°: the Mini's 82.1° diagonal lens across a 16:9 frame from the full sensor), `--no-video` (faster).
A 10-minute flight takes about 5 minutes on the Mac.

**Tested** on a recorded simulated mission turned into an MP4 with a DJI-style SRT (2,535 frames): 5 alerts on the
3 faults, none false, each 2.3–5.8 m from its fault; the same as `tools/eval_mission.py` gives with the drone's own
heading. A 4K H.265 clip runs at about 30 frames per second.

## Limits

- Flat ground: positions assume the fence is at the take-off height.
- The SRT has no heading or gimbal angle; turning on the spot or changing the gimbal mid-flight puts positions off.
- The DJI live view (RTMP from the RC 2, 720p) is not wired to the Jetson yet; this is for recorded video.
