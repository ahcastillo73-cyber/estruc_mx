"""Traductor del modelo a PyNite (análisis lineal dentro de la aplicación).

PyNite usa Y vertical; el modelo usa Z vertical. Se convierte con
(x, y, z) del modelo -> (x, z, -y) en PyNite, que es una rotación propia,
así que los ejes locales de las barras quedan iguales a los de `Edificio.ejes_locales`.

Se analiza la malla de `modelo/malla.py`: los muros y losas son cuadriláteros `Quad3D` de PyNite
(membrana isoparamétrica más placa DKMQ) y las barras que pasan por la malla, tramos.
"""

from __future__ import annotations

import math

from Pynite import FEModel3D

import numpy as np

from ..modelo import Edificio, masas_nodales
from ..modelo.malla import Malla, discretizar
from ..modelo.masas import G, peso_lineal
from .comun import combinaciones_efectivas
from .resultados import Modos, Resultados


def _a_pynite(v):
    x, y, z = v
    return x, z, -y


def _de_pynite(v):
    xp, yp, zp = v
    return xp, -zp, yp


_DIR_DIST = {"X": ("FX", 1.0), "Y": ("FZ", -1.0), "Z": ("FY", 1.0)}


def construir(modelo: Edificio, malla: Malla | None = None) -> FEModel3D:
    malla = malla or discretizar(modelo)
    fem = FEModel3D()
    for m in modelo.materiales:
        # Densidad 0: la masa la reparte modelo/masas.py igual para todos los motores.
        fem.add_material(m.nombre, m.E, m.G, m.nu, 0.0)
    for s in modelo.secciones:
        # Iy de PyNite = menor (I22), Iz de PyNite = mayor (I33)
        fem.add_section(s.nombre, s.A, s.I22, s.I33, s.J)
    for s in modelo.secciones_area:
        m = modelo.material(s.material)
        E = m.E * s.mod_rigidez
        fem.add_material(_material_area(s.nombre), E, E / (2 * (1 + m.nu)), m.nu, 0.0)
    for nid, p in malla.nodos.items():
        fem.add_node(nid, *_a_pynite(p))
    for nid, (ux, uy, uz, rx, ry, rz) in malla.apoyos.items():
        fem.def_support(nid, ux, uz, uy, rx, rz, ry)
    for seg in malla.segmentos:
        b = modelo.barra(seg.barra)
        s = modelo.seccion(b.seccion)
        fem.add_member(seg.id, seg.i, seg.j, s.material, s.nombre, rotation=b.rotacion)
    espesor = {s.nombre: s.espesor for s in modelo.secciones_area}
    seccion = {a.id: a.seccion for a in modelo.areas}
    for e in malla.elementos:
        sec = seccion[e.area]
        fem.add_quad(e.id, *e.nodos, espesor[sec], _material_area(sec))

    for c in modelo.cargas_nodales:
        fx, fy, fz, mx, my, mz = c.fuerzas
        F = _a_pynite((fx, fy, fz))
        M = _a_pynite((mx, my, mz))
        for direc, val in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"), (*F, *M)):
            if val:
                fem.add_node_load(c.nodo, direc, val, case=c.patron)
    for c in modelo.cargas_distribuidas:
        direc, signo = _DIR_DIST[c.direccion]
        for seg in malla.segmentos_de(c.barra):
            fem.add_member_dist_load(seg.id, direc, signo * c.w, signo * c.w, case=c.patron)
    for patron, tabla in malla.cargas_area.items():
        for nid, F in tabla.items():
            for direc, val in zip(("FX", "FY", "FZ"), _a_pynite(F)):
                if val:
                    fem.add_node_load(nid, direc, float(val), case=patron)
    for p in modelo.patrones:
        if p.peso_propio:
            # Peso propio: carga hacia abajo (−Y de PyNite) en los tramos y en los nodos de las áreas
            for seg in malla.segmentos:
                w = p.peso_propio * peso_lineal(modelo, seg.barra)
                if w:
                    fem.add_member_dist_load(seg.id, "FY", -w, -w, case=p.nombre)
            for nid, peso in malla.peso_areas.items():
                fem.add_node_load(nid, "FY", -p.peso_propio * peso, case=p.nombre)

    for co in combinaciones_efectivas(modelo):
        fem.add_load_combo(co.nombre, dict(co.factores))
    return fem


def _material_area(seccion: str) -> str:
    return f"{seccion} (área)"


def _fuerzas_quads(fem: FEModel3D, caso: str) -> dict[str, list[float]]:
    """Fuerzas que los nodos ejercen sobre cada cuadrilátero, en ejes globales del modelo:
    por nodo [FX, FY, FZ, MX, MY, MZ], 24 valores."""
    out = {}
    for nombre, q in fem.quads.items():
        F = (q.Ke() @ q.D(caso)).ravel()
        v: list[float] = []
        for k in range(4):
            v += [*_de_pynite(F[6 * k:6 * k + 3]), *_de_pynite(F[6 * k + 3:6 * k + 6])]
        out[nombre] = [float(x) for x in v]
    return out


def analizar(modelo: Edificio) -> Resultados:
    """Análisis estático lineal de todas las combinaciones."""
    malla = discretizar(modelo)
    fem = construir(modelo, malla)
    fem.analyze_linear(check_statics=False)

    res = Resultados(motor="pynite")
    for co in combinaciones_efectivas(modelo):
        k = co.nombre
        res.desplazamientos[k] = {}
        res.reacciones[k] = {}
        for nid, n in fem.nodes.items():
            d = _de_pynite((n.DX[k], n.DY[k], n.DZ[k]))
            r = _de_pynite((n.RX[k], n.RY[k], n.RZ[k]))
            res.desplazamientos[k][nid] = [*d, *r]
        for nid in malla.apoyos:
            n = fem.nodes[nid]
            F = _de_pynite((n.RxnFX[k], n.RxnFY[k], n.RxnFZ[k]))
            M = _de_pynite((n.RxnMX[k], n.RxnMY[k], n.RxnMZ[k]))
            res.reacciones[k][nid] = [*F, *M]
        if malla.elementos:
            res.fuerzas_elementos[k] = _fuerzas_quads(fem, k)
    return res


_CASO_MASA = "__masa__"


def modal(modelo: Edificio, n_modos: int = 12) -> Modos:
    """Análisis modal con las masas nodales de `masas_nodales` (traslacionales)."""
    malla = discretizar(modelo)
    masas = masas_nodales(modelo, malla)
    if not masas:
        raise ValueError("el modelo no tiene masa: define fuente_masa, peso propio o masas nodales")
    fem = construir(modelo, malla)
    for nodo, m in masas.items():
        # PyNite convierte en masa las cargas en la dirección vertical (su eje Y)
        fem.add_node_load(nodo, "FY", -m * G, case=_CASO_MASA)
    fem.add_load_combo(_CASO_MASA, {_CASO_MASA: 1.0})
    fem.analyze_modal(num_modes=n_modos, mass_combo_name=_CASO_MASA, mass_direction="Y", gravity=G)

    res = Modos(motor="pynite")
    orden = sorted(range(len(fem.frequencies)), key=lambda i: fem.frequencies[i])
    for i in orden:
        k = f"Mode {i + 1}"
        res.periodos.append(1.0 / float(fem.frequencies[i]) if fem.frequencies[i] > 0 else math.inf)
        forma = {}
        for nid, n in fem.nodes.items():
            d = _de_pynite((n.DX[k], n.DY[k], n.DZ[k]))
            r = _de_pynite((n.RX[k], n.RY[k], n.RZ[k]))
            forma[nid] = [float(v) for v in (*d, *r)]
        res.formas.append(forma)
        if malla.elementos:
            res.fuerzas_elementos.append(_fuerzas_quads(fem, k))
    return res
