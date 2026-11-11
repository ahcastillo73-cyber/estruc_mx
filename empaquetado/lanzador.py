"""Punto de entrada de los instaladores (PyInstaller).

Un solo ejecutable hace tres cosas:

- Sin argumentos, o con solo un archivo .json, abre la aplicación de escritorio si
  está incluida; si no, muestra la ayuda de la línea de comandos.
- Con una orden (`analizar`, `reporte`, ...) se comporta como `estruc-mx`.
- Con un script .py como primer argumento lo ejecuta. Así funciona el motor OpenSees,
  que se llama a sí mismo con `sys.executable modelo_opensees.py`: dentro del
  instalador `sys.executable` es este programa y no un intérprete de Python.

`--verificar` importa todos los componentes y sale; lo usa la CI para probar que el
paquete está completo.
"""

from __future__ import annotations

import importlib
import importlib.util
import multiprocessing
import os
import runpy
import sys


def _hay_gui() -> bool:
    try:
        return importlib.util.find_spec("estruc_mx.app.ventana") is not None
    except ModuleNotFoundError:
        return False


def _verificar() -> int:
    modulos = [
        "estruc_mx.cli",
        "estruc_mx.motores.pynite",
        "estruc_mx.motores.opensees",
        "estruc_mx.reporte.pdf",
        "estruc_mx.reporte.word",
        "openseespy.opensees",
        "pyvista",
        "matplotlib",
        "reportlab",
        "docx",
    ]
    if _hay_gui():
        modulos += ["PySide6.QtWidgets", "pyvistaqt", "estruc_mx.app.ventana"]
    fallos = 0
    for m in modulos:
        try:
            importlib.import_module(m)
            print(f"ok     {m}")
        except Exception as e:  # noqa: BLE001 - se informa cualquier fallo
            fallos += 1
            print(f"FALLA  {m}: {type(e).__name__}: {e}")
    print("interfaz gráfica:", "incluida" if _hay_gui() else "no incluida")
    return 1 if fallos else 0


def main() -> int:
    multiprocessing.freeze_support()
    args = sys.argv[1:]

    if args and args[0].endswith(".py") and os.path.isfile(args[0]):
        sys.argv = args
        sys.path.insert(0, os.path.dirname(os.path.abspath(args[0])))
        runpy.run_path(args[0], run_name="__main__")
        return 0

    if args == ["--verificar"]:
        return _verificar()

    from estruc_mx import cli

    sin_orden = not args or (len(args) == 1 and args[0].lower().endswith(".json"))
    if sin_orden:
        if _hay_gui():
            return cli.main(["gui", *args])
        args = ["--help"]
    try:
        return cli.main(args) or 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


if __name__ == "__main__":
    sys.exit(main())
