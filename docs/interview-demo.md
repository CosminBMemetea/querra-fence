# Interview demo: 5 minutes, simulation to confirmed alert

What it shows: a drone camera in simulation, the fence detector running on the Jetson GPU under ROS 2, alerts that need
5 of 8 frames to agree on the ground, and the real sensors (radar, GPS, cameras) on the same robot software stack.

## Before the call (10 minutes)

1. Jetson on, on the same network as the Mac. Panel: `http://mmx-desktop.local:8080` (or `http://192.168.1.163:8080`).
2. On the Jetson: `cd /ssd/querra/ros2 && ./ros.sh doctor` (all green), then `./ros.sh demo`. Or press **Demo: sim +
   detector** in the panel's ROS 2 card.
3. Foxglove app on the Mac: **Open connection → Foxglove WebSocket → `ws://192.168.1.163:8765`**, then **Layout →
   Import from file → `ros2/foxglove/querra-layout.json`**. Wait until the alert count reaches 3 or more.
4. Optional live sim: on the Mac `./start.sh headless` in the sim folder, then `tools/cam_stream.sh`, and on the Jetson
   `./ros.sh stop && ./ros.sh demo tcp://<mac-ip>:5601`. Only if there are 5 spare minutes to test it first.
5. Have the screen share on Foxglove, with the panel in a second tab.

## The script

| Time | Show | Say |
| --- | --- | --- |
| 0:00 | README top | Electric fences on a farm; a drone inspects them so the farmer does not walk 5 km. Three faults matter: broken wire, fallen post, branch on the wire. |
| 0:30 | Architecture diagram (README, ROS 2 section) | Sensors on a Jetson Orin Nano. Services own the hardware; ROS 2 nodes are clients, so nothing fights over a camera or serial port. Same topics from simulation or real sensors. |
| 1:00 | Foxglove: detections image | PX4 + Gazebo farm. The camera stream reaches the Jetson, YOLO11n runs as a TensorRT FP16 engine on the GPU: 15 Hz, about 26 ms from JPEG to boxes. Latency plot underneath. |
| 2:00 | Foxglove: map + alerts panel | A single frame is not an alert. 5 of the last 8 frames must agree within 5 m on the ground; this cut false alarms in the simulated mission from 33 to 6, all real faults still found. Each alert has class, position and confidence. |
| 2:45 | Panel: radar card with heatmap, GPS card | Real sensors on the bench: LD2450 radar with an occupancy heatmap, u-blox GPS with a 3D fix, both cameras live. |
| 3:30 | Panel: ROS 2 card, Record 10 s, bag list | Field data as rosbag2 MCAP on the SSD, downloadable, opened in Foxglove later. Same panel starts and stops data collection on a phone in the field. |
| 4:15 | docs/retraining-log.md | The model was retrained twice because it missed scenarios (thin broken wires, other colours); held-out test set, numbers per release. |
| 4:45 | docs/ros2.md, phase 3 | Next: PX4 over uXRCE-DDS so alerts use the vehicle's own pose, then re-fly a confirmed fault at low altitude. |

## If something fails

- **Foxglove does not connect:** check `./ros.sh status`; restart with `./ros.sh stop && ./ros.sh demo` (about 20 s).
- **Jetson or network down:** open the recorded bag in Foxglove (**Open local file**):
  `querra-demo-sim-20261119-1744_0.mcap` (95 s, 31 MB, simulation topics, detections and alerts only). Copy it from
  `/ssd/querra/bags/` to the Mac before the call; the layout works the same with the bag.
- **Everything down:** the README GIF and `docs/ros2.md` tables tell the same story.

## Risks to say out loud if asked

- Sim-to-real gap: the model is trained on synthetic farms; real fence images are next (data collection is ready).
- Ten alerts on the mission are three real faults and seven false ones; the confirmation rule and more real data are
  the levers.
- Sensor mounting offsets in TF are placeholders until measured on the airframe.
