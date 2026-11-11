"""Compara OpenSeesPy con PyNite en análisis lineal: deben dar lo mismo."""

import pytest

pytest.importorskip("openseespy.opensees", reason="openseespy no está instalado")

from conftest import construir_marco  # noqa: E402

from estruc_mx.motores import opensees, pynite  # noqa: E402


@pytest.mark.parametrize("rotacion", [0.0, 90.0, 30.0])
def test_opensees_y_pynite_coinciden(rotacion):
    m = construir_marco(rotacion_columnas=rotacion)
    rp = pynite.analizar(m)
    ro = opensees.analizar(m)
    for combo in rp.combinaciones:
        for gdl in range(6):
            nodo, ref = rp.desplazamiento_maximo(combo, gdl)
            assert ro.desplazamientos[combo][nodo][gdl] == pytest.approx(ref, rel=1e-4, abs=1e-9), (combo, gdl, nodo)
        for nodo, reac in rp.reacciones[combo].items():
            assert ro.reacciones[combo][nodo] == pytest.approx(reac, rel=1e-4, abs=1e-6), (combo, nodo)


def test_script_generado_es_autonomo(marco, tmp_path):
    texto = opensees.generar_script(marco)
    assert "import openseespy.opensees as ops" in texto
    compile(texto, "modelo_opensees.py", "exec")
