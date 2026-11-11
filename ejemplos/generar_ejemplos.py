"""Regenera los modelos de ejemplo en JSON: python ejemplos/generar_ejemplos.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from conftest import construir_marco  # noqa: E402

construir_marco().guardar(str(Path(__file__).with_name("marco_3niveles.json")))
print("ejemplos/marco_3niveles.json actualizado")
