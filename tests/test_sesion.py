from pathlib import Path

import pytest

from estruc_mx.app.sesion import Sesion

EJEMPLO = str(Path(__file__).resolve().parent.parent / "ejemplos" / "marco_3niveles.json")


def test_flujo_completo_de_una_sesion(tmp_path):
    s = Sesion()
    with pytest.raises(ValueError, match="no hay modelo"):
        s.analizar_estatico()
    s.abrir(EJEMPLO)
    assert dict(s.resumen().filas)["Barras"] == 39

    s.analizar_estatico()
    reac = s.tabla_reacciones("1.1CM+SX")
    assert reac.filas[-1][0] == "Suma" and reac.filas[-1][1] == pytest.approx(-180.0, abs=0.01)
    assert len(s.tabla_desplazamientos("CM").filas) == 24

    s.analizar_espectral("X", n_modos=9)  # hace el modal si falta
    assert len(s.tabla_modal().filas) == 9
    assert [f[0] for f in s.tabla_derivas("X").filas] == [3.5, 6.5, 9.5]

    s.motor = "pynite"
    destino = tmp_path / "copia.json"
    s.guardar(str(destino))
    assert destino.exists() and s.ruta == str(destino)
    s.exportar_script(str(tmp_path / "m.py"))
    assert "openseespy" in (tmp_path / "m.py").read_text(encoding="utf-8")
