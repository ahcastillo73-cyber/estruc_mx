"""Diafragmas rígidos, replicar entre niveles, editar y dividir muros, y cargas dibujadas."""

import numpy as np
import pytest
from conftest import construir_marco
from edificios import edificio_muros

from estruc_mx.modelo import CargaNodal, Diafragma, Edificio, Editor, Rejilla, masas_nodales
from estruc_mx.modelo.diafragmas import centros_de_masa
from estruc_mx.modelo.malla import discretizar
from estruc_mx.motores import pynite


def con_diafragmas(m: Edificio) -> Edificio:
    m = m.model_copy(deep=True)
    zs = sorted({n.z for n in m.nodos})[1:]
    m.diafragmas = [Diafragma(nombre=f"D{k}", z=z) for k, z in enumerate(zs, 1)]
    return Edificio.model_validate(m.model_dump())


# --- diafragmas: modelo y centro de masa ----------------------------------------------
def test_diafragma_repetido_es_invalido(marco):
    d = marco.model_dump()
    d["diafragmas"] = [{"nombre": "A", "z": 3.5}, {"nombre": "B", "z": 3.5}]
    with pytest.raises(ValueError, match="ya hay otro diafragma"):
        Edificio.model_validate(d)


def test_centro_de_masa_y_esclavos(marco):
    m = con_diafragmas(marco)
    malla = discretizar(m)
    masas = masas_nodales(m, malla)
    assert [d.nombre for d in malla.diafragmas] == ["D1", "D2", "D3"]
    for d in malla.diafragmas:
        assert len(d.esclavos) == 6  # 3 × 2 cruces por nivel; la base (apoyos) no entra
        xy = np.array([malla.nodos[n][:2] for n in d.esclavos])
        w = np.array([masas[n] for n in d.esclavos])
        assert d.masa == pytest.approx(w.sum())
        assert d.centro[:2] == pytest.approx(w @ xy / w.sum())
    # Marco simétrico en Y: el centro de masa queda a la mitad
    assert centros_de_masa(m)["D1"][1] == pytest.approx(2.5)


def test_diafragma_sin_nodos_se_avisa(marco):
    m = marco.model_copy(update={"diafragmas": [Diafragma(nombre="Aire", z=50.0)]})
    malla = discretizar(Edificio.model_validate(m.model_dump()))
    assert not malla.diafragmas and "Diafragma Aire" in malla.avisos[0]


# --- diafragmas: motores ------------------------------------------------------------------
def test_diafragma_mueve_el_piso_como_cuerpo_rigido(marco):
    m = con_diafragmas(marco)
    r = pynite.analizar(m)
    malla = discretizar(m)
    for co in ("1.1CM+SX", "1.1CM+SY"):
        tabla = r.desplazamientos[co]
        for d in malla.diafragmas:
            ux, uy, *_, rz = tabla[d.maestro]
            for n in d.esclavos:
                dx, dy = malla.nodos[n][:2] - d.centro[:2]
                assert tabla[n][0] == pytest.approx(ux - rz * dy, abs=1e-8)
                assert tabla[n][1] == pytest.approx(uy + rz * dx, abs=1e-8)
                assert tabla[n][5] == pytest.approx(rz, rel=1e-5)
    # La gravedad casi no cambia (solo se impide el acortamiento axial de las vigas)
    sin = pynite.analizar(marco).desplazamientos["CM"]
    con = r.desplazamientos["CM"]
    assert max(abs(sin[n][2] - con[n][2]) for n in sin) < 0.02 * max(abs(v[2]) for v in sin.values())


def _comparar(m, tol_rel):
    from estruc_mx.motores import opensees

    rp, ro = pynite.analizar(m), opensees.analizar(m)
    for co in ro.combinaciones:
        dp, do = rp.desplazamientos[co], ro.desplazamientos[co]
        assert set(do) == set(dp)
        escala = max(abs(v[g]) for v in do.values() for g in range(3))
        assert max(abs(dp[n][g] - do[n][g]) for n in do for g in range(3)) < tol_rel * escala
    return rp, ro


def test_diafragma_pynite_igual_a_opensees_en_marco(marco):
    pytest.importorskip("openseespy")
    from estruc_mx.motores import opensees

    m = con_diafragmas(marco)
    _comparar(m, 1e-5)
    Tp, To = pynite.modal(m, 6).periodos, opensees.modal(m, 6).periodos
    assert Tp == pytest.approx(To, rel=1e-4)
    # El diafragma cambia los modos de torsión y los superiores
    assert opensees.modal(marco, 6).periodos[3] > 1.5 * To[3]


def test_diafragma_con_muros_y_losas_en_ambos_motores():
    pytest.importorskip("openseespy")
    m = con_diafragmas(edificio_muros())
    # Los motores difieren un poco en las cáscaras (como sin diafragma), no por el diafragma
    rp, ro = _comparar(m, 0.12)
    sx = rp.desplazamientos["CM+SX"]
    for d in discretizar(m).diafragmas:
        assert ro.desplazamientos["CM+SX"][d.maestro][0] == pytest.approx(sx[d.maestro][0], rel=0.05)


def test_script_opensees_usa_rigidDiaphragm(marco):
    from estruc_mx.motores.opensees import generar_script

    s = generar_script(con_diafragmas(marco))
    assert s.count("ops.rigidDiaphragm(3,") == 3 and "D1:CM" in s


# --- replicar -----------------------------------------------------------------------------
@pytest.fixture
def editor():
    ed = Editor()
    ed.nuevo("Prueba", Rejilla.regular([6.0, 4.0], [5.0], [3.0, 3.0, 3.0]))
    ed.marco_desde_rejilla("C40x40", "V25x50", niveles=["N1"])
    return ed


def test_replicar_un_piso_a_otros_niveles_con_cargas(editor):
    editor.agregar_muro((0, 0), (6, 0), 0.0, 3.0, "Muro tabique 14")
    editor.agregar_losa((0, 0), (6, 5), 3.0, "Losa 10")
    editor.asignar_carga_area(["L1"], "CM", "Z", -5.0)
    vigas = [b.id for b in editor.modelo.barras if b.tipo == "viga"]
    editor.asignar_carga_distribuida(vigas, "CV", "Z", -3.0)
    m = editor.modelo
    todo = dict(barras=[b.id for b in m.barras], areas=[a.id for a in m.areas])
    n = editor.replicar_a_niveles("N1", ["N2", "N3"], **todo)
    assert n == {"nodos": 12, "barras": 26, "areas": 4}
    m = editor.modelo
    assert {a.id for a in m.areas} == {"M1", "M2", "M3", "L1", "L2", "L3"}
    assert len(m.cargas_area) == 3 and len(m.cargas_distribuidas) == 3 * len(vigas)
    # Los nodos de los niveles de arriba no se apoyan; los de la base ya existían
    assert len(m.apoyos) == 6
    assert {m.nodo(n).z for a in m.areas if a.tipo == "muro" for n in m.area(a.id).nodos} == {0.0, 3.0, 6.0, 9.0}
    # Replicar otra vez no duplica nada
    assert editor.replicar_a_niveles("N1", ["N2", "N3"], **todo) == {"nodos": 0, "barras": 0, "areas": 0}
    assert len(editor.modelo.cargas_area) == 3


def test_replicar_lineal_en_planta_copia_apoyos(editor):
    m = editor.modelo
    columnas_a = [b.id for b in m.barras if b.tipo == "columna" and m.nodo(b.i).x == 0.0]
    editor.asignar_carga_nodal(["A1-N1"], "CV", (0, 0, -10, 0, 0, 0))
    n = editor.replicar([(-5.0, 0, 0), (-10.0, 0, 0)], nodos=["A1-N1"], barras=columnas_a)
    assert n["barras"] == 4 and n["nodos"] == 8
    m = editor.modelo
    base = [x for x in m.nodos if x.z == 0.0 and x.x < 0]
    assert len(base) == 4 and all(x.id in {a.nodo for a in m.apoyos} for x in base)
    assert len([c for c in m.cargas_nodales if c.patron == "CV"]) == 3
    with pytest.raises(ValueError, match="cero"):
        editor.replicar([(0, 0, 0)], nodos=["A1-N1"])


def test_replicar_se_deshace_en_un_paso(editor):
    antes = editor.modelo
    editor.replicar_a_niveles("N1", ["N2", "N3"], barras=[b.id for b in antes.barras])
    editor.deshacer()
    assert editor.modelo is antes


# --- editar y dividir muros -----------------------------------------------------------------
def test_editar_muro_lo_mueve_y_limpia_nodos(editor):
    mid = editor.agregar_muro((0, 0), (6, 0), 0.0, 3.0, "Muro tabique 14")
    editor.asignar_carga_area([mid], "CM", "Y", 1.0)
    editor.agregar_muro((2, 1), (4, 1), 0.0, 3.0, "Muro tabique 14")  # nodos que luego quedan sueltos
    m2 = editor.modelo.areas[-1].id
    n_antes = len(editor.modelo.nodos)
    editor.editar_muro(m2, (6, 0), (6, 5), 0.0, 3.0)
    m = editor.modelo
    assert m.area(m2).nodos == ("B1-Base", "B2-Base", "B2-N1", "B1-N1")
    assert len(m.nodos) == n_antes - 4  # los cuatro nodos del muro viejo ya no se usan
    assert all(a.nodo in {n.id for n in m.nodos} for a in m.apoyos)
    # Cambiar la altura: de la base al N2
    editor.editar_muro(mid, (0, 0), (6, 0), 0.0, 6.0)
    assert {editor.modelo.nodo(n).z for n in editor.modelo.area(mid).nodos} == {0.0, 6.0}
    assert editor.modelo.cargas_area[0].area == mid
    with pytest.raises(ValueError, match="z_sup"):
        editor.editar_muro(mid, (0, 0), (6, 0), 3.0, 3.0)


def test_dividir_muro_da_el_mismo_resultado():
    ed = Editor()
    ed.nuevo("Muro", Rejilla.regular([6.0], [5.0], [3.0]))
    ed.marco_desde_rejilla("C40x40", "V25x50")
    mid = ed.agregar_muro((0, 0), (6, 0), 0.0, 3.0, "Muro concreto 15")
    ed.asignar_carga_area([mid], "CM", "Y", 2.0)
    ed.definir_malla(0.5)
    m = ed.modelo.model_copy(deep=True)
    m.cargas_nodales.append(CargaNodal(patron="CV", nodo="B1-N1", fuerzas=(100.0, 0, 0, 0, 0, 0)))
    ed.cargar(Edificio.model_validate(m.model_dump()))
    entero = pynite.analizar(ed.modelo)

    ids = ed.dividir_area(mid, 3, 2)
    m = ed.modelo
    assert len(ids) == 6 and ids[0] == mid and len(m.cargas_area) == 6
    # La base del muro sigue empotrada en los nodos nuevos
    base = [n.id for n in m.nodos if n.z == 0.0 and n.y == 0.0]
    assert len(base) == 4 and set(base) <= {a.nodo for a in m.apoyos}
    dividido = pynite.analizar(m)
    for co in entero.combinaciones:
        for n in ("B1-N1", "A1-N1", "B2-N1"):
            assert dividido.desplazamientos[co][n][:3] == pytest.approx(entero.desplazamientos[co][n][:3], rel=1e-6, abs=1e-12)


def test_asignar_y_quitar_diafragmas(editor):
    editor.asignar_diafragmas(["N1", "N2"])
    assert [(d.nombre, d.z) for d in editor.modelo.diafragmas] == [("N1", 3.0), ("N2", 6.0)]
    editor.asignar_diafragmas([9.0])
    assert editor.modelo.diafragmas[-1].nombre == "N3"
    editor.asignar_diafragmas(["N2"], solo_estos=True)
    assert [d.nombre for d in editor.modelo.diafragmas] == ["N2"]
    editor.quitar_diafragmas()
    assert editor.modelo.diafragmas == []
    with pytest.raises(ValueError, match="no existe"):
        editor.asignar_diafragmas(["N9"])


# --- cargas dibujadas ---------------------------------------------------------------------
def test_flechas_de_cargas():
    from estruc_mx.visual.vista3d import flechas_cargas

    m = construir_marco()
    f = flechas_cargas(m, "CM", largo=1.0)
    vigas = sum(c.patron == "CM" for c in m.cargas_distribuidas)
    assert len(f["barra"]) == 5 * vigas and len(f["barra"].textos) == vigas
    assert f["barra"].textos[0] == "-20 kN/m"
    # Las flechas apuntan hacia abajo y su punta toca la barra
    assert np.allclose(f["barra"].vectores, [0, 0, -1.0])
    b = m.barra(m.cargas_distribuidas[0].barra)
    assert np.allclose(f["barra"].origenes[0] + f["barra"].vectores[0], m.nodo(b.i).coords)
    sx = flechas_cargas(m, "SX", largo=1.0)["nodal"]
    assert len(sx) == 3 and sx.textos == ["30 kN", "60 kN", "90 kN"]
    assert np.linalg.norm(sx.vectores, axis=1) == pytest.approx([1 / 3, 2 / 3, 1.0])
    areas = flechas_cargas(edificio_muros(), "CV")["area"]
    assert len(areas) == 9 * 4 and areas.textos[0] == "-2 kN/m²"


def test_malla_de_flechas():
    pytest.importorskip("pyvista")
    from estruc_mx.visual.vista3d import flechas_cargas, malla_flechas

    f = flechas_cargas(construir_marco(), "SX")
    assert malla_flechas(f["nodal"]).n_points > 0
    assert malla_flechas(f["barra"]) is None
