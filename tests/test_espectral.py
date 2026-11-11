import math

import pytest

from estruc_mx.analisis.espectral import coeficientes_cqc, espectral, propiedades_modales
from estruc_mx.modelo import (
    Apoyo,
    Barra,
    Edificio,
    EspectroNTC,
    EspectroTabular,
    MasaNodal,
    Material,
    Nodo,
    SeccionRectangular,
    masas_nodales,
)
from estruc_mx.motores import pynite

E, L, M = 2.0e7, 3.0, 10.0


def columna_con_masa():
    return Edificio(
        nombre="oscilador",
        materiales=[Material(nombre="m", E=E, nu=0.2, peso_vol=24.0)],
        secciones=[SeccionRectangular(nombre="s", material="m", b=0.3, h=0.5)],
        nodos=[Nodo(id="A", x=0, y=0, z=0), Nodo(id="B", x=0, y=0, z=L)],
        barras=[Barra(id="col", tipo="columna", i="A", j="B", seccion="s")],
        apoyos=[Apoyo(nodo="A")],
        masas_nodales=[MasaNodal(nodo="B", masa=M)],
        peso_propio_en_masa=False,
        espectro=EspectroTabular(T=[0.0, 10.0], Sa=[0.3, 0.3]),
    )


def periodo_exacto(I):
    return 2 * math.pi * math.sqrt(M / (3 * E * I / L**3))


def motores():
    salida = [("pynite", pynite.modal)]
    try:
        import openseespy.opensees  # noqa: F401

        from estruc_mx.motores import opensees

        salida.append(("opensees", opensees.modal))
    except Exception:
        pass
    return salida


@pytest.mark.parametrize("nombre, modal", motores())
def test_oscilador_de_un_grado_coincide_con_la_solucion_exacta(nombre, modal):
    m = columna_con_masa()
    s = m.secciones[0]
    modos = modal(m, 3)
    T_x, T_y = periodo_exacto(s.I33), periodo_exacto(s.I22)
    # Dos modos laterales (I33 en X, I22 en Y) y uno axial, mucho más corto
    assert sorted(modos.periodos)[-2:] == pytest.approx(sorted([T_x, T_y]), rel=1e-6)

    prop = propiedades_modales(m, modos)
    assert sum(prop.fraccion_masa["X"]) == pytest.approx(1.0, rel=1e-6)

    r = espectral(m, modos, "X")
    w = 2 * math.pi / T_x
    assert r.desplazamientos["B"][0] == pytest.approx(0.3 * 9.80665 / w**2, rel=1e-6)
    assert r.cortante_basal == pytest.approx(M * 0.3 * 9.80665, rel=1e-6)
    assert r.derivas[0].deriva == pytest.approx(r.desplazamientos["B"][0] / L, rel=1e-6)


def test_masas_se_reparten_a_los_extremos(marco):
    masas = masas_nodales(marco)
    peso = sum(-c.w * marco.longitud(marco.barra(c.barra)) for c in marco.cargas_distribuidas)
    peso += sum(
        marco.material(marco.seccion(b.seccion).material).peso_vol * marco.seccion(b.seccion).A * marco.longitud(b)
        for b in marco.barras
    )
    assert sum(masas.values()) == pytest.approx(peso / 9.80665, rel=1e-9)


def test_espectro_ntc_es_continuo_y_sigue_sus_ramas():
    e = EspectroNTC(a0=0.15, c=0.45, Ta=0.4, Tb=1.2, k=0.5)
    assert e.sa(0.0) == pytest.approx(0.15)
    assert e.sa(0.4) == pytest.approx(0.45) and e.sa(0.4 - 1e-9) == pytest.approx(0.45)
    assert e.sa(1.2) == pytest.approx(0.45)
    T = 2.4
    r = (1.2 / T) ** 2
    assert e.sa(T) == pytest.approx(0.45 * (0.5 + 0.5 * r) * r)
    assert EspectroNTC(a0=0.15, c=0.45, Ta=0.4, Tb=1.2, k=0.5, reduccion=3.0).sa(T) == pytest.approx(e.sa(T) / 3)


def test_cqc_es_uno_en_la_diagonal_y_tiende_a_srss_con_periodos_separados():
    rho = coeficientes_cqc([1.0, 0.1])
    assert rho[0, 0] == pytest.approx(1.0) and rho[1, 1] == pytest.approx(1.0)
    assert rho[0, 1] < 0.01


@pytest.mark.parametrize("direccion", ["X", "Y"])
def test_marco_capta_casi_toda_la_masa_y_las_derivas_crecen_con_el_nivel(marco, direccion):
    modos = pynite.modal(marco, 12)
    prop = propiedades_modales(marco, modos)
    assert prop.fraccion_acumulada(direccion)[-1] > 0.95
    r = espectral(marco, modos, direccion)
    assert [d.nivel for d in r.derivas] == [3.5, 6.5, 9.5]
    assert r.cortante_basal > 0
