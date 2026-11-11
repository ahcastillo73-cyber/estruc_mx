# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para los tres sistemas.

    pyinstaller --noconfirm --clean empaquetado/estruc_mx.spec

Deja en dist/estruc-mx/ la aplicación en carpeta (onedir) y, en macOS, también
dist/estruc-mx.app. Los scripts de la CI la convierten en AppImage, .dmg o
instalador de Windows.
"""

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

datas = [(str(RAIZ / "ejemplos" / "marco_3niveles.json"), "ejemplos")]
binaries = []
hiddenimports = collect_submodules("estruc_mx")

# OpenSeesPy carga un binario nativo desde un paquete distinto en cada sistema, y el
# script del motor lo importa en tiempo de ejecución: se incluye completo.
for paquete in ("openseespy", "openseespylinux", "openseespymac", "openseespywin"):
    if importlib.util.find_spec(paquete) is not None:
        d, b, h = collect_all(paquete)
        datas += d
        binaries += b
        hiddenimports += h

# Fuentes de ReportLab y plantilla de python-docx
datas += collect_data_files("reportlab")
datas += collect_data_files("docx")

# La ventana solo existe cuando el PR de la interfaz está en la rama
GUI = importlib.util.find_spec("PySide6") is not None and (
    RAIZ / "src" / "estruc_mx" / "app" / "ventana.py"
).exists()
if GUI:
    hiddenimports += ["pyvistaqt", "PySide6.QtSvg", "vtkmodules.qt.QVTKRenderWindowInteractor"]

a = Analysis(
    [str(RAIZ / "empaquetado" / "lanzador.py")],
    pathex=[str(RAIZ / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

icono = None
if WINDOWS and (RAIZ / "empaquetado" / "windows" / "estruc-mx.ico").exists():
    icono = str(RAIZ / "empaquetado" / "windows" / "estruc-mx.ico")
elif MACOS and (RAIZ / "empaquetado" / "macos" / "estruc-mx.icns").exists():
    icono = str(RAIZ / "empaquetado" / "macos" / "estruc-mx.icns")

ejecutables = [
    EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="estruc-mx",
        # En Windows el principal es de ventana (sin consola negra) si hay interfaz
        console=not (WINDOWS and GUI),
        icon=icono,
        upx=False,
    )
]
if WINDOWS:
    # Para usar desde PowerShell o cmd: misma aplicación, con consola
    ejecutables.append(
        EXE(pyz, a.scripts, [], exclude_binaries=True, name="estruc-mx-cli", console=True, icon=icono, upx=False)
    )

coll = COLLECT(*ejecutables, a.binaries, a.datas, name="estruc-mx", upx=False)

if MACOS:
    app = BUNDLE(
        coll,
        name="estruc-mx.app",
        icon=icono,
        bundle_identifier="mx.estruc.estruc-mx",
        info_plist={
            "CFBundleDisplayName": "estruc-mx",
            "CFBundleShortVersionString": os.environ.get("ESTRUC_VERSION", "0.1.0"),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
