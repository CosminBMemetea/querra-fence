# LD2450 Radar

A live web view of a HiLink LD2450 (24 GHz mmWave, up to 3 targets) read through a USB-serial adapter (CH340).
It runs on the Jetson, and any browser on the network can open the page.

- **Radar:** a top-down ±60° fan with the sensor at the bottom. Targets move smoothly and show their distance.
- **History:** trails, a heatmap of where people spent time, and a 60-second distance chart.
- **Target cards:** distance, angle, left/right and forward offsets, speed, motion (approaching, moving away, crossing, still), how long it has been tracked, and the closest point.
- **Activity feed:** targets appearing and leaving, the sensor being plugged in or unplugged.
- **Sensor controls:** firmware version, and single or multi-target mode, switched from the page.
- **Hot-plug:** unplugging and replugging the adapter needs no restart.

## Install (Debian/Ubuntu, Jetson)

```bash
sudo apt install ./ld2450-radar_1.0.1_all.deb
```

The package:
- starts the `ld2450-radar` service on boot;
- adds **LD2450 Radar** to the app menu;
- serves the page at `http://<jetson>:8077`.

Options such as the port, the serial device or local-only access are in `/etc/default/ld2450-radar`. After editing that file:

```bash
sudo systemctl restart ld2450-radar
```

```bash
systemctl status ld2450-radar        # is it running
journalctl -u ld2450-radar -f        # its log
sudo apt remove ld2450-radar         # uninstall
```

## Run without installing

```bash
python3 server.py                    # auto-detects the CH340
python3 server.py --serial /dev/ttyUSB0 --http 8077
python3 server.py --demo             # synthetic targets, no sensor needed
```

It needs Python 3.8+ and pyserial (`python3-serial`).

## Build the package

On Debian or Ubuntu:

```bash
./build_deb.sh 1.0.1                 # → dist/ld2450-radar_1.0.1_all.deb
```

## Wiring

| LD2450 | CH340 |
|---|---|
| 5V | 5V |
| GND | GND |
| TX | RXD |
| RX | TXD |

The LD2450 talks at 256000 baud, 8N1, and sends about 10 frames a second.

- **"No data" on the page:** usually TX and RX are not crossed, or the sensor has no 5 V.
- **"Sensor unplugged":** the adapter is not on USB.

## API

| Endpoint | What it returns |
|---|---|
| `GET /state` | The latest frame as JSON: up to 3 targets with x, y in mm and speed in cm/s, plus sensor status. |
| `GET /events` | Server-Sent Events, one message per frame. |
| `POST /mode?set=multi\|single` | Switches the sensor's tracking mode. |
