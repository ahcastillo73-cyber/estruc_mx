import pytest

from estruc_mx.modelo import Apoyo, Barra, CargaNodal, Edificio, Material, Nodo, PatronCarga, SeccionRectangular
from estruc_mx.motores import pynite


def voladizo(fuerzas):
    return Edificio(
        nombre="voladizo",
        materiales=[Material(nombre="m", E=2.0e7, nu=0.2)],
        secciones=[SeccionRectangular(nombre="s", material="m", b=0.3, h=0.5)],
        nodos=[Nodo(id="A", x=0, y=0, z=0), Nodo(id="B", x=0, y=0, z=3.0)],
        barras=[Barra(id="col", tipo="columna", i="A", j="B", seccion="s")],
        apoyos=[Apoyo(nodo="A")],
        patrones=[PatronCarga(nombre="P")],
        cargas_nodales=[CargaNodal(patron="P", nodo="B", fuerzas=fuerzas)],
    )


def test_columna_en_voladizo_coincide_con_la_solucion_exacta():
    m = voladizo((10.0, 0, -100.0, 0, 0, 0))
    s = m.secciones[0]
    E, L = 2.0e7, 3.0
    r = pynite.analizar(m)
    ux, uy, uz = r.desplazamientos["P"]["B"][:3]
    # Columna que sube: eje local y = -X, así que la carga en X flexiona alrededor de z (I33).
    assert ux == pytest.approx(10.0 * L**3 / (3 * E * s.I33), rel=1e-6)
    assert uy == pytest.approx(0.0, abs=1e-12)
    assert uz == pytest.approx(-100.0 * L / (E * s.A), rel=1e-6)
    fx, fy, fz = r.reacciones["P"]["A"][:3]
    assert (fx, fz) == (pytest.approx(-10.0), pytest.approx(100.0))


def test_carga_en_y_usa_la_inercia_menor():
    m = voladizo((0, 10.0, 0, 0, 0, 0))
    s = m.secciones[0]
    r = pynite.analizar(m)
    assert r.desplazamientos["P"]["B"][1] == pytest.approx(10.0 * 27 / (3 * 2.0e7 * s.I22), rel=1e-6)


def test_marco_cumple_el_equilibrio(marco):
    r = pynite.analizar(marco)
    sx = sum(v[0] for v in r.reacciones["1.1CM+SX"].values())
    assert sx == pytest.approx(-(30 + 60 + 90), rel=1e-6)
    peso = sum(-c.w * marco.longitud(marco.barra(c.barra)) for c in marco.cargas_distribuidas)
    assert sum(v[2] for v in r.reacciones["CM"].values()) == pytest.approx(peso, rel=1e-6)
