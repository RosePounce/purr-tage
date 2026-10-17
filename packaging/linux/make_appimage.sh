#!/usr/bin/env bash
# Assemble an AppImage from the package produced by PyInstaller.
# An AppImage is a single file, runnable on most distributions without
# installing anything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist/Purrtage"
APPDIR="$ROOT/build/AppDir"
VERSION="${1:-dev}"
ARCH="${ARCH:-x86_64}"

[ -d "$DIST" ] || { echo "Package not found: $DIST" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/512x512/apps"

cp -a "$DIST/." "$APPDIR/usr/bin/"
cp "$ROOT/packaging/linux/purrtage.desktop" \
   "$APPDIR/usr/share/applications/purrtage.desktop"
cp "$ROOT/packaging/linux/purrtage.desktop" "$APPDIR/purrtage.desktop"
cp "$ROOT/packaging/icon.png" \
   "$APPDIR/usr/share/icons/hicolor/512x512/apps/purrtage.png"
cp "$ROOT/packaging/icon.png" "$APPDIR/purrtage.png"

cat > "$APPDIR/AppRun" <<'LAUNCHER'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Purrtage" "$@"
LAUNCHER
chmod +x "$APPDIR/AppRun"

TOOL="$ROOT/build/appimagetool"
if [ ! -x "$TOOL" ]; then
  echo "Downloading appimagetool..."
  curl -sSL -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$TOOL"
fi

OUTPUT="$ROOT/dist/Purrtage-${VERSION}-${ARCH}.AppImage"
# --appimage-extract-and-run: no need for FUSE, which continuous integration
# containers usually do not have.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"
echo "AppImage: $OUTPUT"
