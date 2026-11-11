"""Discretización del modelo para los motores: muros y losas en elementos de cáscara.

Ambos motores (PyNite y OpenSees) analizan exactamente la misma malla, que sale de aquí:

- Cada muro o losa se divide en n × m cuadriláteros de cuatro nodos, con n y m tales que
  ningún lado pase de `Edificio.tamano_malla`. Las esquinas son los nodos del modelo; los
  nodos interiores se generan y se nombran `<área>:<i>,<j>`.
- Los nodos generados que caen en el mismo punto se unen, así dos áreas que comparten un
  borde con la misma longitud comparten sus nodos (un muro con la losa de arriba, dos losas
  vecinas).
- Las barras que pasan por nodos generados (la viga sobre un muro, la del borde de una losa)
  se parten en tramos, para que trabajen junto con el área.
- Los nodos generados sobre el borde entre dos apoyos iguales heredan ese apoyo (la base de
  un muro empotrado queda empotrada en toda su longitud).
- Las cargas por m² se reparten a los nodos de cada elemento, una cuarta parte a cada uno
  (exacto para elementos rectangulares).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .edificio import Area, Edificio

TOLERANCIA = 1e-6  # m


@dataclass
class Segmento:
    """Tramo de una barra entre dos nodos de la malla."""

    id: str
    barra: str
    i: str
    j: str


@dataclass
class Elemento:
    """Cuadrilátero de cáscara de la malla de un área."""

    id: str
    area: str
    nodos: tuple[str, str, str, str]


@dataclass
class Malla:
    # Todos los nodos del análisis: primero los del modelo, en su orden, luego los generados
    nodos: dict[str, np.ndarray] = field(default_factory=dict)
    generados: set[str] = field(default_factory=set)
    segmentos: list[Segmento] = field(default_factory=list)
    elementos: list[Elemento] = field(default_factory=list)
    # nodo -> (UX, UY, UZ, RX, RY, RZ), incluidos los heredados por los nodos generados
    apoyos: dict[str, tuple[bool, ...]] = field(default_factory=dict)
    # patrón -> nodo -> [FX, FY, FZ] de las cargas por m²
    cargas_area: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    # nodo -> peso propio de muros y losas (kN), para la masa y los patrones con peso propio
    peso_areas: dict[str, float] = field(default_factory=dict)
    # área -> matriz (n + 1, m + 1) de ids de nodos
    rejillas: dict[str, list[list[str]]] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    def segmentos_de(self, barra: str) -> list[Segmento]:
        return [s for s in self.segmentos if s.barra == barra]

    def elementos_de(self, area: str) -> list[Elemento]:
        return [e for e in self.elementos if e.area == area]


def divisiones(esquinas: np.ndarray, tamano: float) -> tuple[int, int]:
    """Divisiones (n a lo largo de 0→1, m a lo largo de 0→3) de un cuadrilátero."""
    c = esquinas
    l1 = max(np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[3]))
    l2 = max(np.linalg.norm(c[3] - c[0]), np.linalg.norm(c[2] - c[1]))
    return max(1, math.ceil(l1 / tamano - 1e-9)), max(1, math.ceil(l2 / tamano - 1e-9))


def punto(esquinas: np.ndarray, s: float, t: float) -> np.ndarray:
    """Interpolación bilineal: s de la esquina 0 a la 1, t de la 0 a la 3."""
    c = esquinas
    return (1 - s) * (1 - t) * c[0] + s * (1 - t) * c[1] + s * t * c[2] + (1 - s) * t * c[3]


def superficie_cuad(p: np.ndarray) -> float:
    return 0.5 * float(np.linalg.norm(np.cross(p[2] - p[0], p[3] - p[1])))


def _clave(p: np.ndarray) -> tuple[int, int, int]:
    return tuple(int(round(v / TOLERANCIA)) for v in p)


def discretizar(modelo: Edificio) -> Malla:
    m = Malla()
    por_punto: dict[tuple[int, int, int], str] = {}
    for n in modelo.nodos:
        m.nodos[n.id] = n.coords
        por_punto.setdefault(_clave(n.coords), n.id)
    for a in modelo.apoyos:
        m.apoyos[a.nodo] = tuple(a.restricciones)

    def nodo_en(p: np.ndarray, nombre: str) -> str:
        k = _clave(p)
        if k in por_punto:
            return por_punto[k]
        while nombre in m.nodos:
            nombre += "'"
        m.nodos[nombre] = p
        m.generados.add(nombre)
        por_punto[k] = nombre
        return nombre

    # --- muros y losas ---------------------------------------------------------------
    for a in modelo.areas:
        c = modelo.esquinas(a)
        n1, n2 = divisiones(c, modelo.tamano_malla)
        ids = [[""] * (n2 + 1) for _ in range(n1 + 1)]
        esquinas = {(0, 0): 0, (n1, 0): 1, (n1, n2): 2, (0, n2): 3}
        for i in range(n1 + 1):
            for j in range(n2 + 1):
                if (i, j) in esquinas:
                    ids[i][j] = a.nodos[esquinas[(i, j)]]
                else:
                    ids[i][j] = nodo_en(punto(c, i / n1, j / n2), f"{a.id}:{i},{j}")
        m.rejillas[a.id] = ids
        for i in range(n1):
            for j in range(n2):
                m.elementos.append(Elemento(
                    id=f"{a.id}#{i},{j}", area=a.id,
                    nodos=(ids[i][j], ids[i + 1][j], ids[i + 1][j + 1], ids[i][j + 1]),
                ))
        _heredar_apoyos(m, a, ids)

    _avisar_nodos_sueltos(modelo, m)

    # --- barras partidas por los nodos generados ---------------------------------------
    gen = sorted(m.generados)
    G = np.array([m.nodos[g] for g in gen]).reshape(-1, 3)
    for b in modelo.barras:
        a, z = m.nodos[b.i], m.nodos[b.j]
        intermedios: list[tuple[float, str]] = []
        if len(G):
            d = z - a
            L2 = float(d @ d)
            t = (G - a) @ d / L2
            dist = np.linalg.norm(G - a - t[:, None] * d, axis=1)
            L = math.sqrt(L2)
            for k in np.nonzero((dist < 10 * TOLERANCIA) & (t * L > 10 * TOLERANCIA) & ((1 - t) * L > 10 * TOLERANCIA))[0]:
                intermedios.append((float(t[k]), gen[k]))
        if not intermedios:
            m.segmentos.append(Segmento(id=b.id, barra=b.id, i=b.i, j=b.j))
            continue
        cadena = [b.i] + [g for _, g in sorted(intermedios)] + [b.j]
        for k, (p, q) in enumerate(zip(cadena, cadena[1:]), start=1):
            m.segmentos.append(Segmento(id=f"{b.id}~{k}", barra=b.id, i=p, j=q))

    # --- cargas y peso de las áreas ---------------------------------------------------
    elems = {}
    for e in m.elementos:
        elems.setdefault(e.area, []).append(e)
    pesos = {s.nombre: modelo.material(s.material).peso_vol * s.espesor for s in modelo.secciones_area}
    for a in modelo.areas:
        for e in elems.get(a.id, []):
            cuarto = superficie_cuad(np.array([m.nodos[n] for n in e.nodos])) / 4.0
            for n in e.nodos:
                if pesos[a.seccion]:
                    m.peso_areas[n] = m.peso_areas.get(n, 0.0) + pesos[a.seccion] * cuarto
    for c in modelo.cargas_area:
        g = "XYZ".index(c.direccion)
        tabla = m.cargas_area.setdefault(c.patron, {})
        for e in elems.get(c.area, []):
            cuarto = superficie_cuad(np.array([m.nodos[n] for n in e.nodos])) / 4.0
            for n in e.nodos:
                v = tabla.setdefault(n, np.zeros(3))
                v[g] += c.w * cuarto
    return m


def _heredar_apoyos(m: Malla, a: Area, ids: list[list[str]]) -> None:
    n1, n2 = len(ids) - 1, len(ids[0]) - 1
    bordes = [
        [ids[i][0] for i in range(n1 + 1)],
        [ids[n1][j] for j in range(n2 + 1)],
        [ids[i][n2] for i in range(n1 + 1)],
        [ids[0][j] for j in range(n2 + 1)],
    ]
    for borde in bordes:
        ra, rb = m.apoyos.get(borde[0]), m.apoyos.get(borde[-1])
        if ra is not None and ra == rb:
            for n in borde[1:-1]:
                if n in m.generados:
                    m.apoyos.setdefault(n, ra)


def _avisar_nodos_sueltos(modelo: Edificio, m: Malla) -> None:
    """Avisa de nodos del modelo que tocan un área sin ser nodo de su malla: no quedan unidos."""
    en_malla = {n for e in m.elementos for n in e.nodos}
    P = np.array([n.coords for n in modelo.nodos]).reshape(-1, 3)
    ids = [n.id for n in modelo.nodos]
    for a in modelo.areas:
        c = modelo.esquinas(a)
        e1, e2, e3 = modelo.ejes_area(a)
        d = P - c[0]
        cerca = np.abs(d @ e3) < 10 * TOLERANCIA
        if not cerca.any():
            continue
        # dentro del polígono (convexo) en coordenadas del plano
        q = np.c_[d @ e1, d @ e2]
        cc = np.c_[(c - c[0]) @ e1, (c - c[0]) @ e2]
        dentro = np.ones(len(P), dtype=bool)
        u, v = cc[1] - cc[0], cc[2] - cc[1]
        signo = 1.0 if u[0] * v[1] - u[1] * v[0] > 0 else -1.0
        for k in range(4):
            p0, p1 = cc[k], cc[(k + 1) % 4]
            cruz = (p1[0] - p0[0]) * (q[:, 1] - p0[1]) - (p1[1] - p0[1]) * (q[:, 0] - p0[0])
            dentro &= signo * cruz > -10 * TOLERANCIA
        sueltos = [ids[k] for k in np.nonzero(cerca & dentro)[0] if ids[k] not in en_malla]
        if sueltos:
            m.avisos.append(
                f"{'Muro' if a.tipo == 'muro' else 'Losa'} {a.id}: los nodos {', '.join(sueltos[:5])}"
                f"{'…' if len(sueltos) > 5 else ''} tocan el área pero no coinciden con su malla y no quedan unidos; "
                "divide el área en esos puntos o ajusta el tamaño de malla."
            )
