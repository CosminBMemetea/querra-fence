# Querra Fence desktop launcher (.deb)

`querra-fence-panel_<version>_arm64.deb` puts a **Querra Fence** app in the Jetson's GNOME dock (Ubuntu 22.04 /
JetPack 6). One click opens the panel in its own app window; if the panel is not running, the launcher starts it first
with the same command as the `# querra-panel` crontab line (as `mmx`, from `~/querra-scout-20261107/panel`).

| File | Purpose |
| --- | --- |
| `/usr/bin/querra-fence` | checks `http://localhost:8080/api/status`, starts the panel if needed (up to 20 s), opens `chromium-browser --app=http://localhost:8080/ --class=QuerraFence` with its own profile; falls back to Firefox, then `xdg-open` |
| `/usr/share/applications/querra-fence.desktop` | the launcher, `StartupWMClass=QuerraFence` so the window groups under the dock icon; right-click actions **ROS 2 demo (sim + detector)** and **Foxglove connection info** |
| `/usr/share/icons/hicolor/{scalable,256x256}/apps/querra-fence.{svg,png}` | icon |

`postinst` refreshes the desktop database and icon cache and adds the launcher to `mmx`'s GNOME favourites when a
desktop session is running (otherwise: Activities → search "Querra Fence" → right-click → Add to Favorites). `prerm`
removes it from the favourites. Field-mode autostart, the panel's own files and the radar serial port are not touched.

```bash
# install on the Jetson (needs your sudo password)
sudo apt install ./querra-fence-panel_0.5.1_arm64.deb
# remove
sudo apt remove querra-fence-panel
# build (on the Jetson or any Linux with dpkg-deb; the PNG icon is pre-rendered in querra-fence-256.png)
packaging/deb/build.sh 0.5.1        # -> packaging/deb/dist/
```

`querra-fence --help` lists the options (`--check`, `--ros-demo`, `--foxglove`). Optional overrides go in
`~/.config/querra-fence.conf` (`PANEL_DIR`, `PANEL_PORT`, `ROS_DIR`).
