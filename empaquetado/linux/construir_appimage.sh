#!/usr/bin/env bash
# Convierte dist/estruc-mx (PyInstaller) en estruc-mx-<versión>-x86_64.AppImage
set -euo pipefail
VERSION="${1:?versión}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"
APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/estruc-mx "$APPDIR/usr/bin/"
cp empaquetado/linux/AppRun "$APPDIR/AppRun"
cp empaquetado/linux/estruc-mx.desktop "$APPDIR/"
cp empaquetado/linux/estruc-mx.desktop "$APPDIR/usr/share/applications/"
cp empaquetado/linux/estruc-mx.png "$APPDIR/estruc-mx.png"
cp empaquetado/linux/estruc-mx.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
ln -sf estruc-mx.png "$APPDIR/.DirIcon"
# Licencia y avisos de terceros, también visibles fuera de la carpeta de PyInstaller
mkdir -p "$APPDIR/usr/share/doc/estruc-mx"
cp LICENSE AVISOS_TERCEROS.md "$APPDIR/usr/share/doc/estruc-mx/"

HERRAMIENTA=build/appimagetool-x86_64.AppImage
if [ ! -x "$HERRAMIENTA" ]; then
  curl -fsSL -o "$HERRAMIENTA" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$HERRAMIENTA"
fi
mkdir -p instaladores
# Sin FUSE en la CI: la herramienta se extrae y se ejecuta
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$HERRAMIENTA" --no-appstream "$APPDIR" \
  "instaladores/estruc-mx-${VERSION}-x86_64.AppImage"
