#!/usr/bin/env bash
set -euo pipefail
cd /src
mkdir -p /out

python3 -m PyInstaller --noconfirm --clean --onedir --name OsoStreamRecord \
  --hidden-import=gi.repository.Gtk --hidden-import=gi.repository.Gdk \
  --hidden-import=gi.repository.Gio --hidden-import=gi.repository.Pango \
  --collect-all gi --add-data '/src/oso/locales:oso/locales' \
  --distpath /tmp/oso-dist --workpath /tmp/oso-work \
  /src/build/desktop_entry.py

APPDIR=/tmp/OsoStreamRecord.AppDir
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share" "$APPDIR/usr/lib/girepository-1.0"
cp -a /tmp/oso-dist/OsoStreamRecord/. "$APPDIR/usr/bin/"
cp -a /opt/invisible-playwright-cache "$APPDIR/usr/share/invisible-playwright-cache"
# GI typelibs and GTK 4 schemas used by the introspected Python bindings.
cp -a /usr/lib/x86_64-linux-gnu/girepository-1.0/*.typelib "$APPDIR/usr/lib/girepository-1.0/"
mkdir -p "$APPDIR/usr/share/glib-2.0/schemas"
cp /usr/share/glib-2.0/schemas/gschemas.compiled "$APPDIR/usr/share/glib-2.0/schemas/"
cp /src/build/linux/com.oso.StreamRecord.desktop "$APPDIR/"
cp /src/build/linux/oso-stream-record.svg "$APPDIR/"
cp /src/build/linux/oso-stream-record.svg "$APPDIR/.DirIcon"

export APPIMAGE_EXTRACT_AND_RUN=1
curl -fsSL -o /tmp/linuxdeploy.AppImage 'https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage'
curl -fsSL -o /tmp/appimagetool.AppImage 'https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage'
chmod +x /tmp/linuxdeploy.AppImage /tmp/appimagetool.AppImage
/tmp/linuxdeploy.AppImage --appdir "$APPDIR" \
  --executable "$APPDIR/usr/bin/OsoStreamRecord" \
  --executable /usr/bin/ffmpeg \
  --desktop-file /src/build/linux/com.oso.StreamRecord.desktop \
  --icon-file /src/build/linux/oso-stream-record.svg

# Bind the included browser engine and GI runtime rather than depending on
# user-local Python, PyGObject or patched Firefox installations.
rm -f "$APPDIR/AppRun"
cat > "$APPDIR/AppRun" <<'LAUNCHER'
#!/bin/sh
APPDIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
export INVISIBLE_PLAYWRIGHT_CACHE_DIR="$APPDIR/usr/share/invisible-playwright-cache"
export GI_TYPELIB_PATH="$APPDIR/usr/lib/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas"
export LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/bin/_internal${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$APPDIR/usr/bin:$PATH"
exec "$APPDIR/usr/bin/OsoStreamRecord" "$@"
LAUNCHER
chmod +x "$APPDIR/AppRun"
ARCH=x86_64 /tmp/appimagetool.AppImage "$APPDIR" /out/OsoStreamRecord-x86_64.AppImage
