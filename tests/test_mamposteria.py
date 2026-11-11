"""Mampostería: módulo de cortante, fuerzas de muro con castillos y revisión NTC Mampostería 2023."""

from pathlib import Path

import numpy as np
import pytest

from estruc_mx.analisis.areas import todas_fuerzas_muros
from estruc_mx.analisis.espectral import espectral
from estruc_mx.analisis.pilas import castillos_muros, rigidez_local, todas_fuerzas_pilas
from estruc_mx.analisis.revision_sismica import revisar
from estruc_mx.app import definiciones as dfn
from estruc_mx.diseno.mamposteria import (
    CriteriosMamposteria,
    RevisionMuro,
    cortante_resistente,
    factor_FE,
    momento_resistente,
    revisar_mamposteria,
)
from estruc_mx.modelo import (
    Apoyo,
    Area,
    CargaNodal,
    Edificio,
    Material,
    Nodo,
    PatronCarga,
    PropiedadesMamposteria,
    RefuerzoMuroMamposteria,
    SeccionArea,
)
from estruc_mx.modelo.malla import discretizar
from estruc_mx.motores import pynite
from estruc_mx.normas import ntc_mamposteria as N

CASA = str(Path(__file__).resolve().parent.parent / "ejemplos" / "casa_mamposteria.json")
EM = 900_000.0  # kPa


def muro_mamposteria(G_cortante=None, mod_cortante=1.0, L=4.0, H=2.5, P=10.0):
    return Edificio(
        nombre="muro",
        materiales=[Material(nombre="tabique", tipo="mamposteria", E=EM, nu=0.25, G_cortante=G_cortante)],
        secciones_area=[SeccionArea(nombre="M14", material="tabique", espesor=0.14, mod_cortante=mod_cortante)],
        nodos=[Nodo(id="A", x=0, y=0, z=0), Nodo(id="B", x=L, y=0, z=0), Nodo(id="C", x=L, y=0, z=H),
               Nodo(id="D", x=0, y=0, z=H)],
        areas=[Area(id="M1", nodos=("A", "B", "C", "D"), seccion="M14")],
        apoyos=[Apoyo(nodo="A"), Apoyo(nodo="B")],
        patrones=[PatronCarga(nombre="P")],
        cargas_nodales=[CargaNodal(patron="P", nodo=n, fuerzas=(P / 2, 0, 0, 0, 0, 0)) for n in ("C", "D")],
        tamano_malla=0.25,
    )


# --- módulo de cortante (2.8.6) ------------------------------------------------------
def test_modulo_de_cortante_de_la_mamposteria():
    m = Material(nombre="t", tipo="mamposteria", E=EM, nu=0.25)
    assert m.G == pytest.approx(0.2 * EM)  # ec. 2.8.6.4.1
    assert Material(nombre="t", tipo="mamposteria", E=EM, G_cortante=1e5).G == 1e5
    assert Material(nombre="c", tipo="concreto", E=2e7, nu=0.2).G == pytest.approx(2e7 / 2.4)
    mod = muro_mamposteria(mod_cortante=0.5)
    E, nu, G = mod.modulos_area(mod.secciones_area[0])
    assert (E, nu, G) == pytest.approx((EM, 0.25, 0.1 * EM))  # agrietado, 3.1.1.2.3


def test_gm_en_los_dos_motores():
    """El muro en voladizo es más flexible con Gm = 0.2·Em y ambos motores dan lo mismo; la
    diferencia con el isótropo es la parte de cortante de la flecha."""
    from estruc_mx.motores import opensees

    pytest.importorskip("openseespy")
    L, H, P, t = 4.0, 2.5, 10.0, 0.14
    iso = muro_mamposteria(G_cortante=EM / 2.5)
    gm = muro_mamposteria()
    u = {}
    for nombre, mot in (("pynite", pynite), ("opensees", opensees)):
        for clave, mod in (("iso", iso), ("gm", gm)):
            r = mot.analizar(mod)
            u[nombre, clave] = r.desplazamientos["P"]["C"][0]
    assert u["pynite", "gm"] == pytest.approx(u["opensees", "gm"], rel=0.03)
    assert u["pynite", "iso"] == pytest.approx(u["opensees", "iso"], rel=0.03)
    # Flecha por cortante, 1.2·P·H/(G·A): su diferencia entre ambos G es la de las flechas
    dif = 1.2 * P * H / (L * t) * (1 / (0.2 * EM) - 1 / (0.4 * EM))
    assert u["pynite", "gm"] - u["pynite", "iso"] == pytest.approx(dif, rel=0.15)


def test_esfuerzo_cortante_con_gm():
    from estruc_mx.analisis.areas import esfuerzos_areas

    m = muro_mamposteria()
    r = pynite.analizar(m)
    esf = esfuerzos_areas(m, discretizar(m), r.desplazamientos["P"])["M1"]
    # Con Gm el flujo de cortante promedio sigue equilibrando la carga: Σ N12 ≈ P / L
    n12 = np.mean([abs(v[2]) for v in esf.values()])
    assert n12 == pytest.approx(10.0 / 4.0, rel=0.25)


# --- fuerzas de muro con castillos ------------------------------------------------------
@pytest.fixture(scope="module")
def casa():
    m = Edificio.cargar(CASA)
    est = pynite.analizar(m)
    modos = pynite.modal(m, 12)
    resp = {d: espectral(m, modos, d) for d in "XY"}
    rev = revisar(m, modos, resp, pynite)
    return m, est, modos, resp, rev


def test_rigidez_local_simetrica_y_axial():
    k = rigidez_local(2e7, 8e6, 0.0225, 4.2e-5, 4.2e-5, 7e-5, 2.6)
    assert np.allclose(k, k.T)
    assert k[0, 0] == pytest.approx(2e7 * 0.0225 / 2.6)
    # Movimiento de cuerpo rígido: sin fuerzas
    u = np.array([1, 2, 3, 0, 0, 0] * 2, dtype=float)
    assert np.allclose(k @ u, 0)


def test_pilas_equilibran_las_reacciones(casa):
    m, est, *_ = casa
    ma = discretizar(m)
    c = "CM+CV"
    f = todas_fuerzas_pilas(m, ma, est.fuerzas_elementos[c], est.desplazamientos[c], c)
    muros = todas_fuerzas_muros(m, ma, est.fuerzas_elementos[c])
    planta_baja = [a.id for a in m.areas if a.tipo == "muro" and min(m.nodo(n).z for n in a.nodos) == 0]
    reaccion = sum(r[2] for r in est.reacciones[c].values())
    # Todos los castillos de planta baja están en extremos de muro: la suma de las pilas es la reacción
    assert -sum(f[a]["P"] for a in planta_baja) == pytest.approx(reaccion, rel=1e-6)
    # Los castillos toman parte de la carga: la pila carga más que el muro solo
    assert all(-f[a]["P"] > -muros[a]["P"] for a in planta_baja)
    cast = castillos_muros(m, ma)
    assert sum(x.fraccion for v in cast.values() for x in v) == pytest.approx(18)  # 9 castillos × 2 niveles


def test_espectral_y_revision_traen_fuerzas_de_pilas(casa):
    m, _, _, resp, rev = casa
    muros = {a.id for a in m.areas if a.tipo == "muro"}
    assert set(resp["X"].fuerzas_pilas) == muros
    assert set(rev.fuerzas_pilas) == muros
    for a in muros:
        assert rev.fuerzas_pilas[a]["V"] >= resp["X"].fuerzas_pilas[a]["V"] - 1e-9
        # El castillo se lleva casi todo el momento de volteo
        assert rev.fuerzas_pilas[a]["M"] > rev.fuerzas_muros[a]["M"]


# --- fórmulas de la norma ------------------------------------------------------------------
def test_interpolaciones_de_la_norma():
    assert N.factor_f(0.1) == 1.5 and N.factor_f(1.2) == 1.0 and N.factor_f(0.6) == pytest.approx(1.25)
    assert N.k0(0.8) == 1.3 and N.k0(1.25) == pytest.approx(1.15) and N.k0(2) == 1.0
    assert N.eta_s(5) == 0.55 and N.eta_s(7.5) == pytest.approx(0.65) and N.eta_s(10) == 0.75
    assert N.fm_de_tabla(12.5, "I", de_concreto=False) == pytest.approx(5.0)  # tabla 2.8.1.4.2
    assert N.fm_de_tabla(10, "II", de_concreto=True) == pytest.approx(4.5)  # tabla 2.8.1.4.1
    # Castillo 15 × 15, f'c = 20 MPa, fy = 412 MPa: As = 0.2·20/412·150·150 = 218 mm²
    assert N.as_min_castillo(20, 412, 150, 150) == pytest.approx(218.4, rel=1e-3)
    # Estribos @ 200 mm: Asc = 1000·200/(412·150) = 3.24 mm²
    assert N.asc_min_estribo(0.20, 412, 0.15) * 1e6 == pytest.approx(3.236, rel=1e-3)
    assert N.fe_ecuacion(0.0, 0.14, 1.0, 0.14 * 30) == 0.0


def test_factor_fe():
    assert factor_FE(0.14, 2.6, extremo=False)[0] == 0.7
    assert factor_FE(0.14, 2.6, extremo=True)[0] == 0.6
    fe, origen = factor_FE(0.10, 2.5, extremo=True)  # H/t = 25 > 20: ec. 3.1.2.3.1
    e = 0.10 / 2 - 0.10 / 3 + 0.10 / 24
    assert fe == pytest.approx((1 - 2 * e / 0.10) * (1 - (2.5 / 3.0) ** 2)) and "3.1.2.3.1" in origen


def test_cortante_resistente_a_mano():
    """Muro de 3 × 2.5 m, t = 14 cm, v'm = 0.3 MPa, P = 100 kN, sin y con refuerzo horizontal."""
    prop = PropiedadesMamposteria(fm=4000, vm=300)
    rm = RevisionMuro("M", "s", "m", "confinada", 0, "X", 0, L=3.0, H=2.5, t=0.14, extremo=False, AT=0.42,
                      P_cortante=100.0)
    cortante_resistente(rm, prop, RefuerzoMuroMamposteria())
    f = 1.5 + (2.5 / 3 - 0.2) / 0.8 * (1.0 - 1.5)
    assert rm.f == pytest.approx(f)
    assert rm.VmR == pytest.approx(0.7 * (0.5 * 300 * 0.42 + 0.3 * 100) * f)
    assert rm.VsR == 0
    # 2 alambres de 5/32" (0.25 cm²) cada 3 hiladas (24 cm), fyh = 500 MPa: ph·fyh = 0.744 MPa,
    # efectivo ≤ 0.1·f'm = 0.4 MPa
    ref = RefuerzoMuroMamposteria(Ash=0.5e-4, sh=0.24, fyh=500e3)
    cortante_resistente(rm, prop, ref)
    assert rm.ph_fyh == pytest.approx(0.5e-4 / (0.24 * 0.14) * 500e3)
    assert rm.ph_fyh_e == pytest.approx(400)
    k1 = 1 - 0.45 * 0.4
    eta = rm.VmR / (0.7 * 400 * 0.42) * (1.3 * k1 - 1) + 0.55
    assert rm.eta == pytest.approx(eta)
    assert rm.VsR == pytest.approx(0.7 * eta * 400 * 0.42)
    # Con tensión no cuenta la mampostería y η = k1·ηs
    rm.P_cortante = -5.0
    cortante_resistente(rm, prop, ref)
    assert rm.VmR == 0 and rm.eta == pytest.approx(k1 * 0.55)


def test_momento_resistente_metodo_optativo():
    Mo, d, PR = 100.0, 3.0, 600.0
    assert momento_resistente(150, PR, Mo, d, 200)[0] == pytest.approx(0.8 * Mo + 0.3 * 150 * d)
    assert momento_resistente(300, PR, Mo, d, 200)[0] == pytest.approx((1.5 * 0.6 * Mo + 0.15 * PR * d) * 0.5)
    assert momento_resistente(-50, PR, Mo, d, 200)[0] == pytest.approx(0.8 * Mo * 0.75)


# --- revisión completa ---------------------------------------------------------------------
def test_revision_de_la_casa(casa):
    m, est, _, resp, rev = casa
    r = revisar_mamposteria(m, est, rev, resp, pynite)
    assert len(r.muros) == 18 and len(r.entrepisos) == 4
    assert r.sistema == "mamposteria_confinada" and r.Q == 2
    assert r.factores_sismo == {"CM": 1.0, "CV": 0.5}
    m1 = r.muro("M1")
    assert m1.extremo and m1.FE == 0.6 and m1.direccion == "X"
    # Muros de 4 m con castillos solo en los extremos: 1.5H = 3.9 m < 4 m (6.2.1.1 a)
    assert not m1.comprobacion("Separación de castillos").cumple
    assert not r.muro("M9").extremo  # muro interior del eje B
    for w in r.muros:
        assert w.Vu is not None and w.Vu > 0 and w.VR > 0 and w.MR is not None
        assert w.comprobacion("Cortante").cumple
        # PR a mano: FR·FE·(f'm·AT + ΣAs·fy)
        As = w.n_castillos * 2.85e-4
        assert w.PR == pytest.approx(0.6 * w.FE * (1500 * w.AT + As * 412e3))
    assert all(e.cumple for e in r.entrepisos)


def test_revision_sin_sismo_y_sin_propiedades():
    m = muro_mamposteria()
    m.patrones[0] = PatronCarga(nombre="P", tipo="muerta")
    m.cargas_nodales = [CargaNodal(patron="P", nodo=n, fuerzas=(0, 0, -50, 0, 0, 0)) for n in ("C", "D")]
    r = revisar_mamposteria(m, pynite.analizar(m), criterios=CriteriosMamposteria())
    w = r.muros[0]
    assert w.Pu == pytest.approx(100, rel=1e-3) and w.Vu is None
    assert any("Tipo II" in a for a in w.avisos) and any("sin refuerzo" in a or "supuso" in a for a in w.avisos)
    assert any("Sin revisión sísmica" in a for a in r.avisos)
    assert w.comprobacion("Carga vertical").cumple


def test_tablas_de_definir_mamposteria():
    m = Edificio.cargar(CASA)
    filas = dfn.filas("mamposteria", m)
    assert filas[0][0] == "Tabique rojo" and filas[0][6] == "1.5"
    filas[0][6] = ""  # sin f'm: de la tabla 2.8.1.4.2 con f'p = 10 MPa
    filas[0][5] = "10"
    mats = dfn.objetos("mamposteria", filas, m)
    assert next(x for x in mats if x.nombre == "Tabique rojo").mamposteria.fm == pytest.approx(4000)
    ref = dfn.filas("refuerzo_muros", m)
    ref[0][dfn.columnas("refuerzo_muros", m).index(next(c for c in dfn.columnas("refuerzo_muros", m)
                                                         if c.titulo.startswith("Ash")))] = "0.5"
    secs = dfn.objetos("refuerzo_muros", ref, m)
    assert secs[[s.nombre for s in secs].index(ref[0][0])].mamposteria.Ash == pytest.approx(0.5e-4)
    # Editar los materiales no borra sus propiedades de mampostería
    mats = dfn.objetos("materiales", dfn.filas("materiales", m), m)
    assert next(x for x in mats if x.nombre == "Tabique rojo").mamposteria is not None
    with pytest.raises(ValueError, match="no existen"):
        dfn.objetos("mamposteria", [["Otro", "bloque_concreto", "no", "1", "I", "", "5", "0.3"]], m)


def test_reporte_incluye_la_revision(casa):
    from estruc_mx.reporte import Opciones
    from estruc_mx.reporte.bloques import Tabla, Titulo
    from estruc_mx.reporte.datos import DatosReporte
    from estruc_mx.reporte.secciones import mamposteria

    m, est, modos, resp, rev = casa
    d = DatosReporte(modelo=m, opciones=Opciones(), estatico=est, modos=modos, espectral=resp, revision=rev)
    d.mamposteria = revisar_mamposteria(m, est, rev, resp, pynite)
    bloques = mamposteria(d)
    assert isinstance(bloques[0], Titulo)
    textos = [c for b in bloques if isinstance(b, Tabla) for f in b.filas for c in f]
    assert any("6.5.2.1" in t for t in textos) and any("6.4.1.1" in t for t in textos)
    assert any("4.1.12.1" in t for t in textos)
