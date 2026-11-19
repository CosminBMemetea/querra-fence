#!/bin/bash
# Builds querra-fence-panel_<version>_arm64.deb. Needs dpkg-deb, plus Chrome (macOS) or rsvg-convert to render the PNG icon.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); VERSION=${1:-0.5.1}
OUT=${OUT:-$HERE/dist}; B=$(mktemp -d); trap 'rm -rf "$B"' EXIT
cp -a "$HERE/src/." "$B/"
SVG=$B/usr/share/icons/hicolor/scalable/apps/querra-fence.svg; PNG=$B/usr/share/icons/hicolor/256x256/apps/querra-fence.png
if [ -f "$HERE/querra-fence-256.png" ]; then cp "$HERE/querra-fence-256.png" "$PNG"
elif command -v rsvg-convert >/dev/null; then rsvg-convert -w 256 -h 256 "$SVG" -o "$PNG"
else echo "need querra-fence-256.png or rsvg-convert" >&2; exit 1; fi
cat > "$B/usr/share/doc/querra-fence-panel/copyright" <<C
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: querra-fence
Files: *
Copyright: 2026 Cosmin Memetea
License: proprietary
 All rights reserved.
C
find "$B" -name '._*' -delete; find "$B" -name .DS_Store -delete
chmod -R u=rwX,go=rX "$B"; chmod 755 "$B"/DEBIAN/post* "$B"/DEBIAN/prerm "$B"/usr/bin/querra-fence
SIZE=$(du -sk --exclude=DEBIAN "$B" 2>/dev/null | cut -f1 || du -sk "$B" | cut -f1)
sed "s/@VERSION@/$VERSION/; s/@SIZE@/$SIZE/" "$HERE/control.in" > "$B/DEBIAN/control"
mkdir -p "$OUT"; dpkg-deb --root-owner-group -Zxz --build "$B" "$OUT/querra-fence-panel_${VERSION}_arm64.deb"
