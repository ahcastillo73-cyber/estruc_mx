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


@pytest.fixture(scope="module")
def edificio_muros_fino():
    from edificios import edificio_muros

    return edificio_muros(tamano_malla=0.5)


def test_muros_y_losas_coinciden_entre_motores(edificio_muros_fino):
    """Misma malla, elementos distintos (PyNite DKMQ, OpenSees ShellMITC4): con malla de 0.5 m
    los desplazamientos y las fuerzas en los muros difieren menos de 3 %."""
    from estruc_mx.analisis.areas import todas_fuerzas_muros
    from estruc_mx.modelo.malla import discretizar

    m = edificio_muros_fino
    ma = discretizar(m)
    rp, ro = pynite.analizar(m), opensees.analizar(m)
    for combo in rp.combinaciones:
        for gdl in range(3):
            nodo, ref = rp.desplazamiento_maximo(combo, gdl)
            assert ro.desplazamientos[combo][nodo][gdl] == pytest.approx(ref, rel=0.03), (combo, gdl, nodo)
        fp = todas_fuerzas_muros(m, ma, rp.fuerzas_elementos[combo])
        fo = todas_fuerzas_muros(m, ma, ro.fuerzas_elementos[combo])
        # Tolerancia relativa a la mayor fuerza de la combinación: los muros poco cargados
        # pueden diferir más en proporción
        escala = {c: max(abs(f[c]) for f in fp.values()) for c in ("P", "V", "M")}
        for muro in fp:
            for c in ("P", "V", "M"):
                assert abs(fo[muro][c] - fp[muro][c]) < 0.03 * escala[c] + 0.01 * escala["P"], (combo, muro, c)
        # Mismas cargas en ambos motores, incluido el peso propio en CM
        for k in range(3):
            assert sum(v[k] for v in ro.reacciones[combo].values()) == pytest.approx(
                sum(v[k] for v in rp.reacciones[combo].values()), rel=1e-6, abs=1e-6)


def test_modal_con_muros_coincide_entre_motores(edificio_muros_fino):
    from estruc_mx.analisis.espectral import espectral

    m = edificio_muros_fino
    mp, mo = pynite.modal(m, 6), opensees.modal(m, 6)
    assert mo.periodos[:3] == pytest.approx(mp.periodos[:3], rel=0.02)
    for d in ("X", "Y"):
        rp, ro = espectral(m, mp, d), espectral(m, mo, d)
        assert ro.cortante_basal == pytest.approx(rp.cortante_basal, rel=0.02)
        assert [x.deriva for x in ro.derivas] == pytest.approx([x.deriva for x in rp.derivas], rel=0.03)
        for muro, f in rp.fuerzas_muros.items():
            assert ro.fuerzas_muros[muro]["V"] == pytest.approx(f["V"], rel=0.05), (d, muro)
