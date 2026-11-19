#!/bin/sh
# Build dist/ld2450-radar_<version>_all.deb (on Debian/Ubuntu: needs dpkg-deb; rsvg-convert optional for PNG icons).
#   ./build_deb.sh [version]
set -eu
umask 022
cd "$(dirname "$0")"
VERSION="${1:-1.0.1}"
P=packaging
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"

install -Dm644 server.py               "$ROOT/opt/ld2450-radar/server.py"
install -Dm644 index.html              "$ROOT/opt/ld2450-radar/index.html"
install -Dm755 $P/ld2450-radar         "$ROOT/usr/bin/ld2450-radar"
install -Dm755 $P/ld2450-radar-open    "$ROOT/usr/bin/ld2450-radar-open"
install -Dm644 $P/ld2450-radar.service "$ROOT/lib/systemd/system/ld2450-radar.service"
install -Dm644 $P/ld2450-radar.default "$ROOT/etc/default/ld2450-radar"
install -Dm644 $P/ld2450-radar.desktop "$ROOT/usr/share/applications/ld2450-radar.desktop"
install -Dm644 $P/ld2450-radar.svg     "$ROOT/usr/share/icons/hicolor/scalable/apps/ld2450-radar.svg"
install -Dm644 README.md               "$ROOT/usr/share/doc/ld2450-radar/README.md"
if command -v rsvg-convert >/dev/null 2>&1; then
  for s in 48 64 128 256; do
    mkdir -p "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps"
    rsvg-convert -w $s -h $s $P/ld2450-radar.svg -o "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps/ld2450-radar.png"
  done
fi

SIZE=$(du -sk "$ROOT" | cut -f1)
mkdir -p "$ROOT/DEBIAN"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" $P/control > "$ROOT/DEBIAN/control"
install -m755 $P/postinst $P/prerm $P/postrm "$ROOT/DEBIAN/"
echo /etc/default/ld2450-radar > "$ROOT/DEBIAN/conffiles"

mkdir -p dist
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "dist/ld2450-radar_${VERSION}_all.deb"
