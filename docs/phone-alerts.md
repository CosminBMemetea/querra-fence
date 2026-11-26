# Phone alerts

A confirmed fence fault arrives on the phone as a notification: what it is, who saw it (the drone or the ground
robot), how sure the model is, the camera frame with the fault boxed, and a map link. It works through **ntfy** (no
account, the quickest start) or **Telegram** (a bot of your own, with a map pin), or both.

```
⚠ Broken wire · ground robot
Alert 3, conf 0.91, 5 frames at 14:07:32
47.123456, 8.654321                         [photo]   tap: the map
```

## Set it up

On the computer that raises the alerts (the Jetson's host for the robots, or the Mac for videos):

**ntfy** (recommended to start: one minute, no account)

```bash
python3 tools/notify.py setup ntfy
```

It makes a private random topic and shows it once. On the phone, install the ntfy app (Google Play, F-Droid or the
App Store), tap **+**, and subscribe to that topic on ntfy.sh. Anyone who knows the topic can read the alerts, so keep
it to yourself.

**Telegram** (a chat with your own bot, and a map pin under each alert)

```bash
python3 tools/notify.py setup telegram
```

In Telegram, ask @BotFather for a new bot (`/newbot`), paste its token when asked (it is not shown), then press
**Start** in the chat with your bot: the tool finds the chat and links it.

Then, for either:

```bash
python3 tools/notify.py test      # a test alert with a photo, at the simulator's home position
python3 tools/notify.py status    # what is set up (no secrets shown)
```

The settings go to `~/.config/querra/notify.json`, readable only by you and never in git.

## Turn it on

| Where | Command |
|---|---|
| The ground robot on the Jetson | `./ros.sh ugv tcp://<mac-ip>:5611 pose:=slam slam:=localization detect:=true notify:=true` |
| The drone on the Jetson | `./ros.sh demo /sim/m1 notify:=true` (the recorded mission) or `./ros.sh demo tcp://<mac-ip>:5601 notify:=true` (live Gazebo) |
| A video on the Mac (phone walk, DJI) | `tools/video_eval.py VIDEO --notify …` ([phone-walk.md](phone-walk.md), [drone-video.md](drone-video.md)) |

On the Jetson, `ros.sh` mounts the settings file read-only into the ROS 2 container, and the `phone_alerts` node
sends a message when it starts, so you know the link works before the patrol. It is off by default: a series of ten
simulated patrols would otherwise send fifty alerts.

## How it behaves

- **Each new alert, once.** The node listens to `/fence/alerts`, where the drone's `alert_confirm` and the ground
  robot's `ugv_alerts` publish each confirmed fault. Repeat sightings of a known fault are not sent, and a restarted
  node does not resend old alerts.
- **The frame that confirmed it.** The alert carries its camera frame's time; the node keeps the last 10 s of frames
  and detections and sends that frame, with the fault boxed thick and other faults thin. It reads the camera's JPEGs
  as they are: the detector does no extra work.
- **No floods.** 5 messages go out at once, then one every 5 minutes; alerts that wait meanwhile go out together as
  one summary with the newest photo (`burst` and `refill_s` in the settings). A storm of false alerts is a few
  messages, not fifty. The public ntfy.sh allows about 250 messages a day.
- **No network, no loss (while it runs).** A failed send is retried for about an hour; in the field the Jetson needs
  a connection (a phone hotspot, a 4G stick), and alerts that waited go out together when it returns. A backend that
  refuses (a wrong token, an unknown chat) is reported in the log and not retried. Alerts waiting in memory are lost
  if the node stops.

## Privacy

- **ntfy.sh** is a public server: it keeps messages for some hours (12 in ntfy's default settings) and photos for 3,
  and anyone with the topic name can subscribe. For more privacy, run your own ntfy server (it can run on the Jetson) and set it up with
  `setup ntfy --server https://your-server`.
- **Telegram** carries the messages through its servers. The bot token lets anyone send as your bot: it stays in the
  settings file, and errors in the logs never show it.
- The photos are of your fence and land; `tools/notify.py test` sends a frame from the simulator with the simulator's
  home position, never your own.

## Tested

Without sending anything out: a local server played ntfy and Telegram for the tests (`tests/test_notify.py`, 20 tests:
the messages, the retries, the refusals, the rate limit, the node choosing the alert's own frame) and for a dry run.
On the simulated walk of forest 700, `video_eval.py --notify` raised its 8 alerts as 6 messages: the first five with
their photos, then the last three as one summary. Not yet: a real phone, and the node on the Jetson.
