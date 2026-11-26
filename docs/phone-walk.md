# The phone walk · real images from the ground robot's view

The ground models were trained and scored in simulation, and there is no robot yet. A phone held where the robot's
camera would be gives the first real ground-view images without the robot or the Jetson. A walk along a real fence
is two tests in one:

1. **Run the ground model over the video** with the robot's alert rule: does it find what is there, and does it raise
   alerts where nothing is wrong?
2. **Label frames of it** ([labelling.md](labelling.md)) for the first real test set: real scores for every model.

## Filming

Film the way the robot's camera sees, so the model gets what it was trained on:

| | Phone | The robot's camera |
|---|---|---|
| Lens | **the 0.5× ultra-wide**, about 100° across or a little more | 100° across |
| Video | 1080p, 30 fps, **landscape** | 640×400, 10 fps |
| Height | about 0.7 m: mid-thigh | 0.70 m |
| Distance to the fence | 1.5–2.5 m, kept steady | 1.9 m (trained on 1.4–2.5 m) |
| Aim | square-on to the fence, level or a little down | sideways, 6° down |
| Speed | a slow walk, about 0.8 m/s | 0.8 m/s |

- **Steady beats handheld.** A phone on something that rolls at 0.7 m (a pram, a wheelbarrow, a bike pushed along)
  is closer to the robot than a phone in your hand. Handheld, keep it in both hands against your thigh.
- Standard video stabilisation is fine. Avoid Cinematic and Action modes: they blur or crop.
- The fence can be on either side: training flips the images, so the direction of walking does not matter.
- Walk the whole fence in one go, corners included. 10 minutes covers about 500 m.
- Different light is worth a second walk: sun and shade, or an overcast day.

**A fence with no faults is a good test.** Every alert on it is a false alert, and in the field false alerts decide
whether anyone keeps reading them. To film faults as well, make them safe and temporary:

- **An electric fence: switch the energiser off first** and check the wires with a fence tester. Switch it back on
  when you are done.
- A branch laid across the wires (`branch`), a wire unclipped from an insulator and left hanging (`wire_break`), a
  spare post laid on the ground under the wires (`fallen_post`).
- Write down each one and the minute in the video when you pass it. Put everything back.

**Privacy:** the footage stays on the Mac, in `~/querra-data/real`, never in the repository. People, houses and car
plates in the frames stay private, so only add a frame to the docs after you have looked at it. Ask before filming
someone else's fence.

## Run the model over it

Copy the video to the Mac, then:

```bash
~/.querra-train-venv/bin/python tools/video_eval.py ~/Movies/IMG_1234.MOV \
    --model ~/querra-data/models/ground-yolo11n-v0.2.pt --no-srt --fps 2
```

- `--fps 2`: at a slow walk two frames a second are 0.4–0.5 m apart, as the robot counts one frame every 0.5 m of
  travel. 5 of 8 frames then span about 4 m of fence, as on the robot.
- `--no-srt`: a phone video has no positions, so the frames alone confirm an alert, and each alert has a time.
- `--class-conf fallen_post=0.5` is the rule the robot uses with ground-v0.1. Run ground-v0.1 with it, and ground-v0.2
  without it: the pair is the first real evidence for or against v0.2.

Results go to `run/video/IMG_1234/`, as for the drone ([drone-video.md](drone-video.md)): `annotated.mp4` with every
box, `alerts.json` with the time and class of each alert, and the frame of each alert in `alerts/`. Check each alert
against your notes: a fault you laid out, or a false alert. A 10-minute walk takes a minute or two on the Mac.

**Tested** on a simulated walk: the 880 frames of forest 700's patrol as a video at 2 fps (a 1 m/s walk, one frame
per 0.5 m). ground-v0.2 raised 8 alerts for the 8 faults, in order and each of the right class, none false.
ground-v0.1 raised 6, missing both fallen posts, and 8 of 8 with `--class-conf fallen_post=0.5`: the same picture as
the scored patrols ([ml/runs/ground-v0.2](../ml/runs/ground-v0.2)).

## Limits

- A person is not a robot: the height and distance wander, and a hand shakes. The scores of a phone walk are a guide
  to the robot's, not the same thing.
- A phone's ultra-wide lens corrects its distortion differently from the simulated camera.
- No positions: an alert is a time in the video, not a place on the map.
