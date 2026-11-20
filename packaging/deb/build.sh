#!/bin/bash
# Builds querra-fence-panel_<version>_arm64.deb. Needs dpkg-deb. The PNG icons are pre-rendered in icons/
# (from the scalable SVG); rsvg-convert, if present, renders any size that is missing.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); VERSION=${1:-0.6.0}
OUT=${OUT:-$HERE/dist}; B=$(mktemp -d); trap 'rm -rf "$B"' EXIT
cp -a "$HERE/src/." "$B/"
SVG=$B/usr/share/icons/hicolor/scalable/apps/querra-fence.svg
for s in 48 64 128 256 512; do
  PNG=$B/usr/share/icons/hicolor/${s}x${s}/apps/querra-fence.png
  mkdir -p "$(dirname "$PNG")"                 # git does not keep empty folders, so create them here
  if [ -f "$HERE/icons/querra-fence-$s.png" ]; then cp "$HERE/icons/querra-fence-$s.png" "$PNG"
  elif command -v rsvg-convert >/dev/null; then rsvg-convert -w "$s" -h "$s" "$SVG" -o "$PNG"
  else echo "need icons/querra-fence-$s.png or rsvg-convert" >&2; exit 1; fi
done
DOC=$B/usr/share/doc/querra-fence-panel; mkdir -p "$DOC"
# DEP-5: the header paragraph and the Files paragraph are separated by a blank line.
cat > "$DOC/copyright" <<C
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: querra-fence

Files: *
Copyright: 2026 Cosmin Memetea
License: proprietary
 All rights reserved.
C
sed -i.bak "s/^VERSION=.*/VERSION=$VERSION/" "$B/usr/bin/querra-fence" && rm -f "$B/usr/bin/querra-fence.bak"
find "$B" -name '._*' -delete; find "$B" -name .DS_Store -delete
chmod -R u=rwX,go=rX "$B"; chmod 755 "$B"/DEBIAN/post* "$B"/DEBIAN/prerm "$B"/usr/bin/querra-fence
SIZE=$(du -sk --exclude=DEBIAN "$B" 2>/dev/null | cut -f1 || du -sk "$B" | cut -f1)
sed "s/@VERSION@/$VERSION/; s/@SIZE@/$SIZE/" "$HERE/control.in" > "$B/DEBIAN/control"
mkdir -p "$OUT"; dpkg-deb --root-owner-group -Zxz --build "$B" "$OUT/querra-fence-panel_${VERSION}_arm64.deb"
