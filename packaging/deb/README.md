# Querra Fence desktop launcher (.deb)

`querra-fence-panel_<version>_arm64.deb` puts a **Querra Fence** app in the Jetson's GNOME dock (Ubuntu 22.04 /
JetPack 6). One click opens the panel in its own app window; if the panel is not running, the launcher starts it first
through the panel's `restart.sh` (as `mmx`, from `~/querra-scout-20261107/panel`), which also clears a hung panel.
A panel started this way lives in the desktop session; the `# querra-panel` crontab line stays the normal start at boot.

| File | Purpose |
| --- | --- |
| `/usr/bin/querra-fence` | checks that `http://localhost:8080/` answers, starts the panel if needed (up to 20 s), opens `chromium-browser --app=http://localhost:8080/ --class=QuerraFence` with its own profile (`--disable-gpu` on Jetson, where snap Chromium cannot use the GPU); if Chromium fails it falls back to Firefox, then `xdg-open`. Browser output goes to `~/.cache/querra-fence.log`. `--ros-demo` sends the panel PIN from `config.json` when one is required |
| `/usr/share/applications/querra-fence.desktop` | the launcher, `StartupWMClass=QuerraFence` so the window groups under the dock icon; right-click actions **ROS 2 demo (sim + detector)** and **Foxglove connection info** |
| `/usr/share/icons/hicolor/{scalable,48x48,64x64,128x128,256x256,512x512}/apps/querra-fence.{svg,png}` | icon (PNGs pre-rendered in `icons/` from the SVG) |

`postinst` refreshes the desktop database and icon cache and, on the first install only, adds the launcher to `mmx`'s
GNOME favourites when a desktop session is running (otherwise: Activities → search "Querra Fence" → right-click → Add to
Favorites); upgrades keep the dock as the user left it. `prerm`
removes it from the favourites. Field-mode autostart, the panel's own files and the radar serial port are not touched.

```bash
# install on the Jetson (needs your sudo password)
sudo apt install ./querra-fence-panel_0.6.0_arm64.deb
# remove
sudo apt remove querra-fence-panel
# build (on the Jetson or any Linux with dpkg-deb; the PNG icons are pre-rendered in icons/)
packaging/deb/build.sh 0.6.0        # -> packaging/deb/dist/
```

`querra-fence --help` lists the options (`--check`, `--ros-demo`, `--foxglove`). Optional overrides go in
`~/.config/querra-fence.conf` (`PANEL_DIR`, `PANEL_PORT`, and `ROS_DIR`, where `--foxglove` looks for the layout file).
