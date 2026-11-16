# Jetson brain: "tell me what you see"

The Jetson looks at the farm through the simulated cameras, reads what the ground station and the drone know,
and answers typed questions out loud. The answers come from a local vision-language model, grounded in live sensor facts
so it does not invent numbers. Without a model it still answers from the facts alone.

```
Mac: simulation                               Jetson: brain                         Mac: browser, shared in the call
Gazebo + PX4 + ground station ──RTSP 8554──▶  frames (RGB, thermal, drone)
state API /state ──────────────HTTP 8095──▶   facts                                 http://JETSON:8090
                                              Ollama vision model + Piper voice ──▶  type a question, hear the answer
```

## One-time setup on the Jetson

1. **Check the system.** `cat /etc/nv_tegra_release` (JetPack 6 shows `R36`). Install ffmpeg: `sudo apt install -y ffmpeg`.
2. **Ollama with a vision model.**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen2.5vl:7b          # about 6 GB; qwen2.5vl:3b if 7b is too slow
   ollama run qwen2.5vl:7b "Say hello in one sentence."
   ollama ps                          # PROCESSOR must say "100% GPU"
   ```
   If it runs on the CPU only, use the Jetson AI Lab Ollama container for your JetPack instead (see their Ollama tutorial).
3. **Piper voice.**
   ```bash
   python3 -m pip install piper-tts
   mkdir -p ~/voices && cd ~/voices && python3 -m piper.download_voices en_US-lessac-medium
   piper -m en_US-lessac-medium --data-dir ~/voices -f /tmp/test.wav -- "Hello, I am the ground station." && aplay /tmp/test.wav
   ```
4. **The brain.** Two files, no Python packages: copy `brain/` to the Jetson, for example
   `scp -r brain USER@JETSON:~/gardian-brain`.

## Network

The simplest setup for the interview is one Ethernet cable between the Mac and the Jetson, so the call's Wi-Fi does not matter.

- **Mac:** System Settings → Network → the Ethernet adapter → Details → TCP/IP → Configure IPv4 *Manually*: `192.168.50.1`, mask `255.255.255.0`.
- **Jetson:**
  ```bash
  sudo nmcli con add type ethernet ifname eth0 con-name gardian ipv4.method manual ipv4.addresses 192.168.50.20/24
  sudo nmcli con up gardian
  ping 192.168.50.1
  ```

Both on the same Wi-Fi also works; then use the addresses each device gets.

## Run it

1. **Mac, simulation:** `GARDIAN_HOST=192.168.50.1 ./start.sh guard --share`
2. **Jetson, brain:**
   ```bash
   python3 ~/gardian-brain/server.py --state http://192.168.50.1:8095 --rtsp rtsp://192.168.50.1:8554 \
       --model qwen2.5vl:7b --voice en_US-lessac-medium --voice-dir ~/voices
   ```
3. **Mac, browser:** open `http://192.168.50.20:8090`. The three cameras appear within a few seconds and the chips at the top
   turn green: model, voice, cameras.
4. **The call:** share that browser window with sound.
   - Zoom: Share Screen → pick the window → tick **Share sound**.
   - Teams: Share → **Include sound** (or *Include computer sound*).
   - Google Meet: Present → **A tab** → pick the tab and keep **Also share tab audio** on.

   Before the interview, check with a friend on a test call that they hear the voice.

## The scenario, minute by minute

| Time | What happens | Good questions |
|---|---|---|
| 0:00–0:45 | Herd grazing, gate open, drone on the pad | "What do you see right now?" · "What does the thermal camera show?" |
| ~0:50 | A cow walks out through the gate; the iToF counts it, the mast camera sees it outside; the drone takes off | "Are any animals outside the fence?" · "Why did the drone take off?" |
| ~1:15 | The top wire breaks at F1; the fence monitor at the far end drops to 0 kV | "Is the fence OK?" |
| 1:30–3:30 | The drone flies the fence and finds F1, F2, F3 and the escaped animals | "What has the drone found?" · "Where exactly is the broken wire?" |
| ~3:45 | The drone lands; the ground station keeps watching | "Summarise what happened." |

## If something goes wrong

- **The model is slow or missing:** the brain answers from the facts automatically; the chip says *facts only*.
- **The Jetson is not reachable:** run the brain on the Mac, `python3 brain/server.py --model none`, and open `http://127.0.0.1:8090`.
  It speaks with the Mac's voice.
- **No sound in the call:** the window was shared without sound; stop sharing and share again with sound on.
- **The scenario is over:** `./stop.sh`, then start again; the next run takes about 40 seconds to come up.

## Two minutes on how it works

- The simulation is the farm: PX4 flies a real X500 mission in Gazebo; the ground station and its cameras are simulated.
- Everything the Jetson gets is what it would get on a farm: RTSP video and a small JSON state API. Real cameras only change the URLs.
- The vision model sees the RGB, thermal and drone frames, but numbers, IDs and voltages come from sensor facts in the prompt,
  which keeps a small edge model from making things up.
- Everything runs locally on the Jetson: no cloud, which matters on a farm with weak internet.
