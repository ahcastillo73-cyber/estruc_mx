"""Traductor del modelo a PyNite (análisis lineal dentro de la aplicación).

PyNite usa Y vertical; el modelo usa Z vertical. Se convierte con
(x, y, z) del modelo -> (x, z, -y) en PyNite, que es una rotación propia,
así que los ejes locales de las barras quedan iguales a los de `Edificio.ejes_locales`.
"""

from __future__ import annotations

from Pynite import FEModel3D

from ..modelo import Edificio
from .comun import combinaciones_efectivas
from .resultados import Resultados


def _a_pynite(v):
    x, y, z = v
    return x, z, -y


def _de_pynite(v):
    xp, yp, zp = v
    return xp, -zp, yp


_DIR_DIST = {"X": ("FX", 1.0), "Y": ("FZ", -1.0), "Z": ("FY", 1.0)}


def construir(modelo: Edificio) -> FEModel3D:
    fem = FEModel3D()
    for m in modelo.materiales:
        fem.add_material(m.nombre, m.E, m.G, m.nu, m.peso_vol / 9.80665)
    for s in modelo.secciones:
        # Iy de PyNite = menor (I22), Iz de PyNite = mayor (I33)
        fem.add_section(s.nombre, s.A, s.I22, s.I33, s.J)
    for n in modelo.nodos:
        fem.add_node(n.id, *_a_pynite((n.x, n.y, n.z)))
    for a in modelo.apoyos:
        ux, uy, uz, rx, ry, rz = a.restricciones
        fem.def_support(a.nodo, ux, uz, uy, rx, rz, ry)
    for b in modelo.barras:
        s = modelo.seccion(b.seccion)
        fem.add_member(b.id, b.i, b.j, s.material, s.nombre, rotation=b.rotacion)

    for c in modelo.cargas_nodales:
        fx, fy, fz, mx, my, mz = c.fuerzas
        F = _a_pynite((fx, fy, fz))
        M = _a_pynite((mx, my, mz))
        for direc, val in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"), (*F, *M)):
            if val:
                fem.add_node_load(c.nodo, direc, val, case=c.patron)
    for c in modelo.cargas_distribuidas:
        direc, signo = _DIR_DIST[c.direccion]
        fem.add_member_dist_load(c.barra, direc, signo * c.w, signo * c.w, case=c.patron)

    for co in combinaciones_efectivas(modelo):
        fem.add_load_combo(co.nombre, dict(co.factores))
    return fem


def analizar(modelo: Edificio) -> Resultados:
    """Análisis estático lineal de todas las combinaciones."""
    fem = construir(modelo)
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
        for a in modelo.apoyos:
            n = fem.nodes[a.nodo]
            F = _de_pynite((n.RxnFX[k], n.RxnFY[k], n.RxnFZ[k]))
            M = _de_pynite((n.RxnMX[k], n.RxnMY[k], n.RxnMZ[k]))
            res.reacciones[k][a.nodo] = [*F, *M]
    return res
