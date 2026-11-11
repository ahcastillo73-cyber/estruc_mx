import numpy as np
import pytest

from estruc_mx.analisis.espectral import espectral
from estruc_mx.analisis.pisos import pisos
from estruc_mx.analisis.revision_sismica import CriteriosSismicos, cargas_torsion, revisar
from estruc_mx.modelo import EspectroNTC, masas_nodales
from estruc_mx.modelo.malla import discretizar
from estruc_mx.motores import pynite
from estruc_mx.normas import ntc_sismo

from conftest import construir_marco
from edificios import edificio_muros


@pytest.fixture(scope="module")
def marco():
    m = construir_marco()
    modos = pynite.modal(m, 6)
    return m, modos, {d: espectral(m, modos, d) for d in "XY"}


@pytest.fixture(scope="module")
def muros():
    m = edificio_muros()
    modos = pynite.modal(m, 8)
    return m, modos, {d: espectral(m, modos, d) for d in "XY"}


def test_a_min_interpola_entre_ts_corto_y_largo():
    assert ntc_sismo.a_min(0.3) == pytest.approx(0.04)
    assert ntc_sismo.a_min(0.75) == pytest.approx(0.05)
    assert ntc_sismo.a_min(2.0, R=2.0) == pytest.approx(0.03)
    assert ntc_sismo.a_min(None) == pytest.approx(0.06)  # sin Ts, el mayor


def test_ks_por_zona():
    assert ntc_sismo.ks("A") == pytest.approx(1 / 6)
    assert ntc_sismo.ks("C") == pytest.approx(1 / 4)
    assert ntc_sismo.ks("B", 0.75) == pytest.approx(1 / 5)
    assert ntc_sismo.ks("B", 2.0) == pytest.approx(1 / 4)  # Ts fuera de 0.5–1.0 s se acota
    with pytest.raises(ValueError):
        ntc_sismo.ks("B")


def test_excentricidad_crece_de_005_a_010():
    assert [ntc_sismo.excentricidad_accidental(i, 3) for i in (1, 2, 3)] == pytest.approx([0.05, 0.075, 0.10])
    assert ntc_sismo.excentricidad_accidental(1, 1) == pytest.approx(0.05)


def test_cortante_del_primer_entrepiso_es_el_basal(marco):
    _, _, r = marco
    for x in r.values():
        assert x.cortantes_entrepiso[0][1] == pytest.approx(x.cortante_basal, rel=1e-9)
        v = [c for _, c in x.cortantes_entrepiso]
        assert v == sorted(v, reverse=True)


def test_centro_de_masa_de_marco_simetrico(marco):
    m, _, _ = marco
    malla = discretizar(m)
    lista = pisos(m, malla, masas_nodales(m, malla))
    assert [p.z for p in lista] == [3.5, 6.5, 9.5]
    for p in lista:
        assert (p.xc, p.yc, p.bx, p.by) == pytest.approx((6.0, 2.5, 12.0, 5.0))


def test_cargas_de_torsion_son_un_par_puro(marco):
    m, _, r = marco
    malla = discretizar(m)
    masas = masas_nodales(m, malla)
    lista = pisos(m, malla, masas)
    rev = revisar(m, marco[1], r, pynite)
    for p, t in zip(lista, rev.torsion["X"]):
        cargas = [c for c in cargas_torsion(m, [p], [t], masas, "T")]
        F = np.array([c.fuerzas for c in cargas])
        xy = np.array([[m.nodo(c.nodo).x - t.xc, m.nodo(c.nodo).y - t.yc] for c in cargas])
        assert F[:, 0].sum() == pytest.approx(0, abs=1e-9) and F[:, 1].sum() == pytest.approx(0, abs=1e-9)
        assert np.sum(xy[:, 0] * F[:, 1] - xy[:, 1] * F[:, 0]) == pytest.approx(t.M0)
        assert t.Ma == pytest.approx(t.V * t.fraccion * 5.0)  # b = 5 m para sismo en X


def test_momentos_de_nivel_suman_los_de_entrepiso(marco):
    # Ec. 2.3.3: la suma de M0 de los niveles de arriba es el momento Ma = V·ea del entrepiso
    m, modos, r = marco
    t = revisar(m, modos, r, pynite).torsion["X"]
    for i in range(len(t)):
        assert sum(x.M0 for x in t[i:]) == pytest.approx(t[i].Ma)


def test_sin_torsion_ni_ortogonal_reproduce_el_espectral(marco):
    m, modos, r = marco
    rev = revisar(m, modos, r, pynite, CriteriosSismicos(torsion=False, ortogonal=0.0))
    for d in "XY":
        assert [x.deriva for x in rev.derivas[d]] == pytest.approx([x.deriva for x in r[d].derivas])


def test_torsion_y_ortogonal_aumentan_las_derivas(muros):
    m, modos, r = muros
    base = revisar(m, modos, r, pynite, CriteriosSismicos(torsion=False, ortogonal=0.0))
    tors = revisar(m, modos, r, pynite, CriteriosSismicos(ortogonal=0.0))
    comp = revisar(m, modos, r, pynite)
    for d in "XY":
        for a, b, c in zip(base.derivas[d], tors.derivas[d], comp.derivas[d]):
            assert a.deriva < b.deriva <= c.deriva + 1e-12
    assert {x.gobierna for v in comp.derivas.values() for x in v} <= {"X + 0.3Y", "Y + 0.3X"}


def test_cortante_minimo_escala_fuerzas_y_no_desplazamientos(muros):
    m, modos, r = muros
    normal = revisar(m, modos, r, pynite)
    alto = revisar(m, modos, r, pynite, CriteriosSismicos(cortante_minimo=1.0))
    cx = alto.cortante["X"]
    assert cx.factor == pytest.approx(cx.W / cx.V0) and cx.factor > 1
    assert [x.deriva for x in alto.derivas["X"]] == pytest.approx([x.deriva for x in normal.derivas["X"]])
    f = min(alto.cortante[d].factor for d in "XY")
    for a, v in alto.fuerzas_muros.items():
        assert v["V"] >= f * normal.fuerzas_muros[a]["V"] * (1 - 1e-9)
    escalado = revisar(m, modos, r, pynite, CriteriosSismicos(cortante_minimo=1.0, escalar_desplazamientos=True))
    assert escalado.derivas["X"][0].deriva > normal.derivas["X"][0].deriva


def test_fuerzas_de_muros_con_torsion_y_100_30(muros):
    m, modos, r = muros
    rev = revisar(m, modos, r, pynite)
    for a, v in rev.fuerzas_muros.items():
        for k, x in v.items():
            assert x >= r["X"].fuerzas_muros[a][k] - 1e-9
            assert x >= r["Y"].fuerzas_muros[a][k] - 1e-9


def test_servicio_con_divisor_o_espectro(marco):
    m, modos, r = marco
    rev = revisar(m, modos, r, pynite, CriteriosSismicos(divisor_servicio=4.0))
    for d in "XY":
        assert [x.deriva for x in rev.derivas_servicio[d]] == pytest.approx([x.deriva / 4.0 for x in rev.derivas[d]])
    sin = revisar(m, modos, r, pynite)
    assert sin.derivas_servicio == {}
    zona = revisar(m, modos, r, pynite, CriteriosSismicos(zona="A"))
    assert [x.deriva for x in zona.derivas_servicio["X"]] == pytest.approx([x.deriva / 6 for x in rev.derivas["X"]])

    m2 = m.model_copy(deep=True)
    e = m.espectro
    m2.espectro_servicio = EspectroNTC(nombre="Servicio", a0=e.a0, c=e.c, Ta=e.Ta, Tb=e.Tb, k=e.k, reduccion=2.0)
    rev2 = revisar(m2, modos, r, pynite)
    for d in "XY":  # misma forma espectral a la mitad: la mitad de la distorsión
        assert [x.deriva for x in rev2.derivas_servicio[d]] == pytest.approx([x.deriva / 2 for x in rev.derivas[d]])


def test_torsion_con_diafragma_rigido_en_el_maestro():
    """Con diafragma, el centro de masa es el del maestro y el momento va como MZ en un nodo
    del piso; ambos motores dan el mismo giro del maestro."""
    from estruc_mx.motores import opensees
    from test_editor_niveles import con_diafragmas

    pytest.importorskip("openseespy")
    m = con_diafragmas(edificio_muros())
    malla = discretizar(m)
    lista = pisos(m, malla, masas_nodales(m, malla))
    for p, d in zip(lista, malla.diafragmas):
        assert p.diafragma is d and (p.xc, p.yc) == pytest.approx(tuple(d.centro[:2]))
    giros = {}
    for motor in (pynite, opensees):
        modos = motor.modal(m, 8)
        r = {d: espectral(m, modos, d) for d in "XY"}
        rev = revisar(m, modos, r, motor)
        assert not any("sin diafragma" in a for a in rev.avisos)
        masas = masas_nodales(m, malla)
        cargas = cargas_torsion(m, lista, rev.torsion["X"], masas, "T")
        assert len(cargas) == len(lista) and all(c.fuerzas[:5] == (0, 0, 0, 0, 0) for c in cargas)
        assert [c.fuerzas[5] for c in cargas] == pytest.approx([t.M0 for t in rev.torsion["X"]])
        giros[motor.__name__] = [x.deriva for x in rev.derivas["X"]]
    a, b = giros.values()
    assert a == pytest.approx(b, rel=0.05)
