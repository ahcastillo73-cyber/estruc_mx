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


def test_modal_y_espectral_coinciden_entre_motores(marco):
    from estruc_mx.analisis.espectral import espectral

    mp = pynite.modal(marco, 9)
    mo = opensees.modal(marco, 9)
    assert mo.periodos == pytest.approx(mp.periodos, rel=1e-4)
    for d in ("X", "Y"):
        rp, ro = espectral(marco, mp, d), espectral(marco, mo, d)
        assert ro.cortante_basal == pytest.approx(rp.cortante_basal, rel=1e-4)
        assert [x.deriva for x in ro.derivas] == pytest.approx([x.deriva for x in rp.derivas], rel=1e-4)
