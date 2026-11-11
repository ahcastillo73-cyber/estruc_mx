"""Muros y losas: modelo, malla, masas, motores y fuerzas en muros."""

import math

import numpy as np
import pytest
from edificios import edificio_muros

from estruc_mx.analisis.areas import esfuerzos_areas, extremos_esfuerzos, todas_fuerzas_muros
from estruc_mx.modelo import (
    Apoyo, Area, CargaArea, CargaNodal, Edificio, Editor, Material, Nodo, PatronCarga, Rejilla, SeccionArea,
    masas_nodales,
)
from estruc_mx.modelo.malla import discretizar
from estruc_mx.modelo.masas import pesos_propios
from estruc_mx.motores import pynite

E, NU, T = 2.0e7, 0.2, 0.15


def muro_voladizo(cargas, L=4.0, H=3.0, tamano=0.5, base=("A", "B")):
    return Edificio(
        nombre="muro",
        materiales=[Material(nombre="c", E=E, nu=NU, peso_vol=24.0)],
        secciones_area=[SeccionArea(nombre="M15", material="c", espesor=T)],
        nodos=[Nodo(id="A", x=0, y=0, z=0), Nodo(id="B", x=L, y=0, z=0), Nodo(id="C", x=L, y=0, z=H), Nodo(id="D", x=0, y=0, z=H)],
        areas=[Area(id="M1", nodos=("A", "B", "C", "D"), seccion="M15")],
        apoyos=[Apoyo(nodo=n) for n in base],
        patrones=[PatronCarga(nombre="P")],
        cargas_nodales=[CargaNodal(patron="P", nodo=n, fuerzas=f) for n, f in cargas],
        tamano_malla=tamano,
    )


# --- modelo ------------------------------------------------------------------------
def test_validacion_de_areas():
    base = muro_voladizo([]).model_dump()
    with pytest.raises(ValueError, match="no están en un plano"):
        d = dict(base, nodos=[*base["nodos"][:3], {"id": "D", "x": 0, "y": 0.5, "z": 3.0}])
        Edificio.model_validate(d)
    with pytest.raises(ValueError, match="perímetro"):
        Edificio.model_validate(dict(base, areas=[{"id": "M1", "nodos": ["A", "C", "B", "D"], "seccion": "M15"}]))
    with pytest.raises(ValueError, match="sección 'X' no existe"):
        Edificio.model_validate(dict(base, areas=[{"id": "M1", "nodos": ["A", "B", "C", "D"], "seccion": "X"}]))
    with pytest.raises(ValueError, match="área 'Z' no existe"):
        Edificio.model_validate(dict(base, cargas_area=[{"patron": "P", "area": "Z", "w": -1}]))


def test_ejes_de_muros_y_losas():
    m = muro_voladizo([])
    e1, e2, e3 = m.ejes_area(m.areas[0])
    assert e2 == pytest.approx([0, 0, 1]) and abs(e1[0]) == pytest.approx(1.0)
    ed = Editor()
    ed.nuevo("x")
    ed.agregar_losa((0, 0), (6, 5), 3.0, "Losa 10")
    losa = ed.modelo.areas[0]
    assert losa.tipo == "losa" and ed.modelo.superficie(losa) == pytest.approx(30.0)
    assert [list(v) for v in ed.modelo.ejes_area(losa)] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


# --- malla -------------------------------------------------------------------------
def test_malla_une_nodos_parte_barras_y_hereda_apoyos():
    m = edificio_muros(tamano_malla=1.0)
    ma = discretizar(m)
    # Muro de 6 × 3 m con malla de 1 m: 6 × 3 elementos
    assert len(ma.elementos_de("M1")) == 18
    # La losa del tablero A–B comparte con el muro M1 los nodos del borde en y = 0
    borde = {n for n, p in ma.nodos.items() if abs(p[1]) < 1e-9 and abs(p[2] - 3.0) < 1e-9 and p[0] <= 6}
    nodos_losa = {n for e in ma.elementos_de("L1") for n in e.nodos}
    nodos_muro = {n for e in ma.elementos_de("M1") for n in e.nodos}
    assert borde <= nodos_losa and borde <= nodos_muro and len(borde) == 7
    # La viga sobre el muro se parte en tramos de 1 m
    viga = next(b for b in m.barras if b.tipo == "viga" and {b.i, b.j} == {"A1-N1", "B1-N1"})
    assert len(ma.segmentos_de(viga.id)) == 6
    # La base del muro queda empotrada en toda su longitud
    base = [n for n, p in ma.nodos.items() if abs(p[1]) < 1e-9 and abs(p[2]) < 1e-9 and p[0] <= 6]
    assert len(base) == 7 and all(ma.apoyos[n] == (True,) * 6 for n in base)
    assert not ma.avisos


def test_masa_incluye_muros_losas_y_cargas_por_m2():
    m = edificio_muros()
    ma = discretizar(m)
    W = sum(masas_nodales(m, ma).values()) * 9.80665
    peso = 0.0
    for a in m.areas:
        s = m.seccion_area(a.seccion)
        peso += m.material(s.material).peso_vol * s.espesor * m.superficie(a)
    for b in m.barras:
        s = m.seccion(b.seccion)
        peso += m.material(s.material).peso_vol * s.A * m.longitud(b)
    losas = sum(m.superficie(a) for a in m.areas if a.tipo == "losa")
    peso += (5.0 + 0.4 * 2.0) * losas
    # La masa de los nodos de la base (apoyados) también cuenta en la suma
    assert W == pytest.approx(peso, rel=1e-9)


def test_aviso_de_nodo_que_toca_el_area_sin_unirse():
    m = muro_voladizo([]).model_dump()
    m["nodos"].append({"id": "X", "x": 1.3, "y": 0, "z": 3.0})  # en el borde superior, fuera de la malla
    assert any("X" in a for a in discretizar(Edificio.model_validate(m)).avisos)


# --- motores y fuerzas ------------------------------------------------------------
def test_muro_en_voladizo_fuera_del_plano_coincide_con_la_placa():
    """Carga fuera del plano en el borde superior: δ ≈ PH³/(3EI) de una placa en voladizo."""
    m = muro_voladizo([("C", (0, 5.0, 0, 0, 0, 0)), ("D", (0, 5.0, 0, 0, 0, 0))], tamano=0.25)
    r = pynite.analizar(m)
    I = 4.0 * T**3 / 12
    viga = 10.0 * 27 / (3 * E * I)
    # La placa es algo más flexible que la viga (ν y cortante), menos de 10 %
    assert r.desplazamientos["P"]["C"][1] == pytest.approx(viga, rel=0.1)
    assert r.desplazamientos["P"]["C"][1] > viga


def test_fuerzas_en_la_base_del_muro_equilibran_las_cargas():
    m = muro_voladizo([("C", (50, 0, 0, 0, 0, 0)), ("D", (50, 0, -200, 0, 0, 0))])
    r = pynite.analizar(m)
    f = todas_fuerzas_muros(m, discretizar(m), r.fuerzas_elementos["P"])["M1"]
    assert f["P"] == pytest.approx(-200.0)
    assert f["V"] == pytest.approx(100.0)
    # 100 kN a 3 m de altura menos 200 kN a 2 m del centro de la base
    assert f["M"] == pytest.approx(100 * 3 - 200 * 2)
    assert f["Vfp"] == pytest.approx(0.0, abs=1e-6) and f["Mfp"] == pytest.approx(0.0, abs=1e-6)


def test_losa_simplemente_apoyada_con_carga_uniforme():
    """Losa cuadrada apoyada en sus cuatro bordes: momento al centro ≈ 0.0479·q·a² (ν = 0.3, Timoshenko)."""
    a, q = 4.0, 10.0
    m = Edificio(
        nombre="losa",
        materiales=[Material(nombre="c", E=E, nu=0.3)],
        secciones_area=[SeccionArea(nombre="L", material="c", tipo="losa", espesor=0.10)],
        nodos=[Nodo(id=k, x=x, y=y, z=0) for k, x, y in (("A", 0, 0), ("B", a, 0), ("C", a, a), ("D", 0, a))],
        areas=[Area(id="L1", tipo="losa", nodos=("A", "B", "C", "D"), seccion="L")],
        apoyos=[Apoyo(nodo=n, restricciones=(True, True, True, False, False, False)) for n in "ABCD"],
        patrones=[PatronCarga(nombre="W")],
        cargas_area=[CargaArea(patron="W", area="L1", w=-q)],
        tamano_malla=0.25,
    )
    r = pynite.analizar(m)
    ma = discretizar(m)
    D = E * 0.1**3 / (12 * (1 - 0.09))
    centro = min(ma.nodos, key=lambda n: np.linalg.norm(ma.nodos[n][:2] - a / 2))
    assert r.desplazamientos["W"][centro][2] == pytest.approx(-0.00406 * q * a**4 / D, rel=0.03)
    ext = extremos_esfuerzos(esfuerzos_areas(m, ma, r.desplazamientos["W"])["L1"])
    assert ext["M11"][1] == pytest.approx(0.0479 * q * a**2, rel=0.05)
    assert ext["M22"][1] == pytest.approx(0.0479 * q * a**2, rel=0.05)
    assert sum(v[2] for v in r.reacciones["W"].values()) == pytest.approx(q * a * a)


def test_edificio_con_muros_cumple_el_equilibrio():
    m = edificio_muros()
    r = pynite.analizar(m)
    ma = discretizar(m)
    losas = sum(m.superficie(a) for a in m.areas if a.tipo == "losa")
    # CM aplica el peso propio de barras, muros y losas (modelo_inicial)
    pp = sum(pesos_propios(m, ma).values())
    assert pp > 0
    assert sum(v[2] for v in r.reacciones["CM+CV"].values()) == pytest.approx(7.0 * losas + pp, rel=1e-6)
    assert sum(v[0] for v in r.reacciones["CM+SX"].values()) == pytest.approx(-150.0, rel=1e-6)
    # El muro de concreto de la planta baja toma buena parte del sismo en X; el resto, las columnas
    f = todas_fuerzas_muros(m, ma, r.fuerzas_elementos["CM+SX"])
    planta_baja = [a.id for a in m.areas if a.tipo == "muro" and min(m.nodo(n).z for n in a.nodos) == 0]
    assert 0.4 * 150 < f[planta_baja[0]]["V"] < 150


def test_tablas_y_derivas_con_muros(tmp_path):
    from estruc_mx.analisis.espectral import espectral

    m = edificio_muros()
    modos = pynite.modal(m, 6)
    r = espectral(m, modos, "Y")
    assert len(r.derivas) == 2 and r.cortante_basal > 0
    assert set(r.fuerzas_muros) == {a.id for a in m.areas if a.tipo == "muro"}
    assert all(v >= 0 for f in r.fuerzas_muros.values() for v in f.values())
    # Un modelo solo de muros (sin columnas) también tiene derivas
    solo = muro_voladizo([("C", (50, 0, 0, 0, 0, 0))]).model_copy(update={"fuente_masa": {"P": 1.0}, "peso_propio_en_masa": True})
    assert math.isfinite(pynite.modal(solo, 2).periodos[0])


# --- editor ------------------------------------------------------------------------
def test_editor_de_muros_y_losas():
    ed = Editor()
    ed.nuevo("x", Rejilla.regular([5.0], [4.0], [3.0]))
    mid = ed.agregar_muro((0, 0), (5, 0), 0.0, 3.0, "Muro tabique 14")
    m = ed.modelo
    assert mid == "M1" and m.area("M1").tipo == "muro"
    assert {a.nodo for a in m.apoyos} == {"A1-Base", "B1-Base"}  # muro en la base: empotrado
    assert ed.agregar_muro((0, 0), (5, 0), 0.0, 3.0, "Muro tabique 14") == "M1"  # no se duplica
    assert ed.losas_desde_rejilla("Losa 10") == 1
    ed.asignar_carga_area(["L1"], "CM", "Z", -4.0)
    ed.editar_nodo("A1-N1", id_nuevo="esq")
    assert "esq" in ed.modelo.area("M1").nodos and "esq" in ed.modelo.area("L1").nodos
    ed.reemplazar("secciones_area", [SeccionArea(nombre="T14", material="Tabique rojo", espesor=0.14),
                                     SeccionArea(nombre="Losa 10", material="Concreto f'c 250", tipo="losa", espesor=0.1)],
                  {"Muro tabique 14": "T14"})
    assert ed.modelo.area("M1").seccion == "T14"
    ed.borrar(nodos=["esq"])
    assert not ed.modelo.areas and not ed.modelo.cargas_area
    ed.deshacer()
    ed.borrar(areas=["L1"])
    assert [a.id for a in ed.modelo.areas] == ["M1"] and not ed.modelo.cargas_area
    with pytest.raises(ValueError):
        ed.agregar_losa((0, 0), (0, 4), 3.0, "Losa 10")


def test_peso_propio_como_carga_no_se_cuenta_dos_veces_en_la_masa():
    m = edificio_muros()
    ma = discretizar(m)
    con = sum(masas_nodales(m, ma).values())
    # Sin peso propio en la masa, entra por CM (que lo aplica con factor 1): la masa no cambia
    sin = m.model_copy(update={"peso_propio_en_masa": False})
    assert sum(masas_nodales(sin, ma).values()) == pytest.approx(con, rel=1e-12)
    # Si CM no lo aplicara, la masa sería menor en el peso propio
    patrones = [p.model_copy(update={"peso_propio": 0.0}) for p in m.patrones]
    nada = m.model_copy(update={"peso_propio_en_masa": False, "patrones": patrones})
    assert (con - sum(masas_nodales(nada, ma).values())) * 9.80665 == pytest.approx(sum(pesos_propios(m, ma).values()))
