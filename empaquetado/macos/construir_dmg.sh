#!/usr/bin/env bash
# Convierte dist/estruc-mx.app (PyInstaller) en estruc-mx-<versión>-macos-arm64.dmg
set -euo pipefail
VERSION="${1:?versión}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"
CARPETA=build/dmg
rm -rf "$CARPETA"
mkdir -p "$CARPETA" instaladores
cp -R dist/estruc-mx.app "$CARPETA/"
ln -s /Applications "$CARPETA/Aplicaciones"
# Sin firma de Apple: PyInstaller firma ad hoc, suficiente para Apple Silicon.
# El primer arranque requiere clic derecho > Abrir (ver README).
hdiutil create -volname "estruc-mx ${VERSION}" -srcfolder "$CARPETA" -ov -format UDZO \
  "instaladores/estruc-mx-${VERSION}-macos-arm64.dmg"
