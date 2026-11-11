"""Fuerzas de cada muro junto con sus castillos («pilas», como las «pier forces» de ETABS).

La NTC Mampostería modela los muros con elementos finitos y los castillos con barras en su eje
(3.2.2.4). Para revisar el muro hacen falta las fuerzas del conjunto: el castillo de concreto,
mucho más rígido axialmente, toma buena parte de la carga vertical y casi todo el momento de
volteo en el plano. Aquí se suman, en la base de cada muro:

- las fuerzas de los elementos de cáscara de la fila inferior (`areas.fuerzas_muro`), y
- las de los tramos de castillo (barras verticales) que arrancan en un nodo del borde inferior
  del muro. Un castillo compartido por k muros del mismo nivel (esquina, intersección) se
  reparte por partes iguales, 1/k a cada uno, que es una aproximación.

Las fuerzas de los castillos salen de los desplazamientos de sus nudos con la matriz de rigidez
elástica de la barra, igual para cualquier motor y también para las formas modales. En los
casos estáticos se añaden las fuerzas de empotramiento de las cargas uniformes de la barra
(peso propio y cargas distribuidas), y el peso propio que la malla asigna a los nodos de la base
del muro (la mitad inferior de la primera fila de elementos), que no pasa por los elementos.

Mismos signos que `areas.fuerzas_muro`: P > 0 tensión; V y M en el plano del muro.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..modelo import Edificio
from ..modelo.malla import TOLERANCIA, Malla, Segmento
from ..modelo.masas import peso_lineal
from ..motores.comun import combinaciones_efectivas
from .areas import COMPONENTES_MURO, BaseMuro, bases_muros, fuerzas_muro


@dataclass
class CastilloMuro:
    segmento: Segmento
    nodo_base: str  # nodo de la malla en la base del muro (extremo inferior del tramo)
    fraccion: float  # parte de sus fuerzas que se asigna al muro
    posicion: float  # coordenada a lo largo del muro desde el centro de la base, m


def nodos_base(base: BaseMuro, malla: Malla) -> list[str]:
    elementos = {e.id: e for e in malla.elementos_de(base.area)}
    return sorted({elementos[eid].nodos[k] for eid, k in base.nodos},
                  key=lambda n: float((malla.nodos[n] - base.centro) @ base.ejes[0]))


def castillos_muros(modelo: Edificio, malla: Malla, bases: dict[str, BaseMuro] | None = None) -> dict[str, list[CastilloMuro]]:
    """muro -> tramos de barra vertical que arrancan en su borde inferior."""
    bases = bases if bases is not None else bases_muros(modelo, malla)
    en_base = {a: nodos_base(b, malla) for a, b in bases.items()}
    # Tramo vertical que sube desde cada nodo
    sube: dict[str, Segmento] = {}
    for sg in malla.segmentos:
        pi, pj = malla.nodos[sg.i], malla.nodos[sg.j]
        d = pj - pi
        if np.hypot(d[0], d[1]) > TOLERANCIA or abs(d[2]) <= TOLERANCIA:
            continue
        abajo = sg.i if d[2] > 0 else sg.j
        sube[abajo] = sg
    usos: dict[str, int] = {}
    for nodos in en_base.values():
        for n in nodos:
            if n in sube:
                usos[n] = usos.get(n, 0) + 1
    out: dict[str, list[CastilloMuro]] = {}
    for a, nodos in en_base.items():
        b = bases[a]
        out[a] = [
            CastilloMuro(sube[n], n, 1.0 / usos[n], float((malla.nodos[n] - b.centro) @ b.ejes[0]))
            for n in nodos if n in sube
        ]
    return out


def rigidez_local(E: float, G: float, A: float, I22: float, I33: float, J: float, L: float) -> np.ndarray:
    """Matriz 12×12 de una barra elástica (Euler-Bernoulli) en ejes locales
    [ux, uy, uz, rx, ry, rz] de cada nudo. I33 trabaja en el plano x-y (giro rz), I22 en el x-z."""
    k = np.zeros((12, 12))
    k[0, 0] = k[6, 6] = E * A / L
    k[0, 6] = k[6, 0] = -E * A / L
    k[3, 3] = k[9, 9] = G * J / L
    k[3, 9] = k[9, 3] = -G * J / L
    a, b, c, d = 12 * E * I33 / L**3, 6 * E * I33 / L**2, 4 * E * I33 / L, 2 * E * I33 / L
    for (i, j), v in {(1, 1): a, (1, 5): b, (1, 7): -a, (1, 11): b, (5, 5): c, (5, 7): -b, (5, 11): d,
                      (7, 7): a, (7, 11): -b, (11, 11): c}.items():
        k[i, j] = k[j, i] = v
    a, b, c, d = 12 * E * I22 / L**3, 6 * E * I22 / L**2, 4 * E * I22 / L, 2 * E * I22 / L
    for (i, j), v in {(2, 2): a, (2, 4): -b, (2, 8): -a, (2, 10): -b, (4, 4): c, (4, 8): b, (4, 10): d,
                      (8, 8): a, (8, 10): b, (10, 10): c}.items():
        k[i, j] = k[j, i] = v
    return k


def fuerzas_segmento(modelo: Edificio, malla: Malla, sg: Segmento, desplazamientos: dict[str, list[float]],
                     carga: np.ndarray | None = None) -> np.ndarray:
    """Fuerzas (12, ejes globales) que los nudos i y j ejercen sobre el tramo, de sus
    desplazamientos; `carga` es una carga uniforme global (kN/m) sobre el tramo."""
    b = modelo.barra(sg.barra)
    s = modelo.seccion(b.seccion)
    m = modelo.material(s.material)
    R = np.array(modelo.ejes_locales(b))
    L = float(np.linalg.norm(malla.nodos[sg.j] - malla.nodos[sg.i]))
    T = np.kron(np.eye(4), R)
    u = np.array([*desplazamientos[sg.i], *desplazamientos[sg.j]], dtype=float)
    f = rigidez_local(m.E, m.G, s.A, s.I22, s.I33, s.J, L) @ (T @ u)
    if carga is not None and np.any(carga):
        qx, qy, qz = R @ carga
        f += np.array([
            -qx * L / 2, -qy * L / 2, -qz * L / 2, 0.0, qz * L**2 / 12, -qy * L**2 / 12,
            -qx * L / 2, -qy * L / 2, -qz * L / 2, 0.0, -qz * L**2 / 12, qy * L**2 / 12,
        ])
    return T.T @ f


def cargas_barras(modelo: Edificio, combinacion: str) -> dict[str, np.ndarray]:
    """barra -> carga uniforme global (kN/m) de la combinación: peso propio y distribuidas."""
    combos = {c.nombre: c for c in combinaciones_efectivas(modelo)}
    if combinacion not in combos:
        return {}
    fac = combos[combinacion].factores
    out: dict[str, np.ndarray] = {}
    pp = sum(fac.get(p.nombre, 0.0) * p.peso_propio for p in modelo.patrones)
    if pp:
        for b in modelo.barras:
            w = peso_lineal(modelo, b.id)
            if w:
                out[b.id] = np.array([0.0, 0.0, -pp * w])
    for c in modelo.cargas_distribuidas:
        k = fac.get(c.patron, 0.0)
        if k:
            v = out.setdefault(c.barra, np.zeros(3))
            v[{"X": 0, "Y": 1, "Z": 2}[c.direccion]] += k * c.w
    return out


def fuerzas_pila(base: BaseMuro, malla: Malla, fuerzas_elementos: dict[str, list[float]],
                 castillos: list[CastilloMuro], modelo: Edificio, desplazamientos: dict[str, list[float]] | None,
                 cargas: dict[str, np.ndarray] | None = None) -> dict[str, float]:
    """P, V, M, Vfp, Mfp, T del muro más sus castillos, en el centro de su base."""
    f = fuerzas_muro(base, malla, fuerzas_elementos) if fuerzas_elementos else dict.fromkeys(COMPONENTES_MURO, 0.0)
    if not castillos or desplazamientos is None:
        return f
    S = np.zeros(3)
    Mo = np.zeros(3)
    for c in castillos:
        sg = c.segmento
        F = fuerzas_segmento(modelo, malla, sg, desplazamientos, (cargas or {}).get(sg.barra))
        k = 0 if c.nodo_base == sg.i else 6
        Fi = F[k:k + 6] * c.fraccion
        p = malla.nodos[c.nodo_base]
        S -= Fi[:3]
        Mo -= Fi[3:] + np.cross(p - base.centro, Fi[:3])
    e1, e2, e3 = base.ejes
    extra = {"P": S @ e2, "V": S @ e1, "M": -(Mo @ e3), "Vfp": S @ e3, "Mfp": Mo @ e1, "T": Mo @ e2}
    return {k: float(f[k] + extra[k]) for k in COMPONENTES_MURO}


def todas_fuerzas_pilas(modelo: Edificio, malla: Malla, fuerzas_elementos: dict[str, list[float]],
                        desplazamientos: dict[str, list[float]] | None, combinacion: str | None = None,
                        bases: dict[str, BaseMuro] | None = None,
                        castillos: dict[str, list[CastilloMuro]] | None = None) -> dict[str, dict[str, float]]:
    """Fuerzas de todas las pilas para un caso estático (`combinacion` para las cargas de las
    barras) o una forma modal (sin `combinacion`)."""
    bases = bases if bases is not None else bases_muros(modelo, malla)
    castillos = castillos if castillos is not None else castillos_muros(modelo, malla, bases)
    cargas = cargas_barras(modelo, combinacion) if combinacion else None
    out = {a: fuerzas_pila(b, malla, fuerzas_elementos, castillos.get(a, []), modelo, desplazamientos, cargas)
           for a, b in bases.items()}
    pp = _factor_peso_propio(modelo, combinacion) if combinacion else 0.0
    if pp:
        for a, b in bases.items():
            out[a]["P"] -= pp * peso_en_base(modelo, malla, b)
    return out


def _factor_peso_propio(modelo: Edificio, combinacion: str) -> float:
    combos = {c.nombre: c for c in combinaciones_efectivas(modelo)}
    if combinacion not in combos:
        return 0.0
    fac = combos[combinacion].factores
    return sum(fac.get(p.nombre, 0.0) * p.peso_propio for p in modelo.patrones)


def peso_en_base(modelo: Edificio, malla: Malla, base: BaseMuro) -> float:
    """Peso propio (kN) de los elementos del muro asignado a sus nodos de la base."""
    a = modelo.area(base.area)
    s = modelo.seccion_area(a.seccion)
    gamma_t = modelo.material(s.material).peso_vol * s.espesor
    if not gamma_t:
        return 0.0
    elementos = {e.id: e for e in malla.elementos_de(base.area)}
    total = 0.0
    for eid, _k in base.nodos:
        p = np.array([malla.nodos[n] for n in elementos[eid].nodos])
        area = 0.5 * float(np.linalg.norm(np.cross(p[2] - p[0], p[3] - p[1])))
        total += gamma_t * area / 4
    return total
