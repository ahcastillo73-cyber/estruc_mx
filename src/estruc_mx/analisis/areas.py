"""Fuerzas en muros y esfuerzos en losas a partir de los resultados de cualquier motor.

Todo se calcula aquí, igual para PyNite y OpenSees:

- **Fuerzas de muro** (como las «pier forces» de ETABS): resultantes en la base de cada muro,
  sumando las fuerzas de los elementos de la fila inferior sobre los nodos de la base. Salen
  del equilibrio de los elementos, así que la suma de las fuerzas de los muros de la planta
  baja más las de las columnas iguala las reacciones.
- **Esfuerzos por unidad de ancho** en el centro de cada elemento (N11, N22, N12 en kN/m;
  M11, M22, M12 en kN·m/m), con las deformaciones de membrana y las curvaturas que dan los
  desplazamientos y giros de sus cuatro nodos interpolados bilinealmente.

Ejes de cada área (ver `Edificio.ejes_area`): en muros 1 horizontal a lo largo del muro, 2
vertical hacia arriba, 3 normal. En losas horizontales 1 = X, 2 = Y y 3 hacia arriba.

Signos:
- P > 0 tensión. V, en la dirección 1 del muro: la fuerza que el muro transmite hacia abajo.
  M (en el plano) > 0 cuando una fuerza en +1 aplicada arriba lo produce.
- M11, M22 > 0 tensionan la cara del lado −3 (la cara inferior de una losa).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..modelo import Edificio
from ..modelo.malla import Malla

COMPONENTES_MURO = ("P", "V", "M", "Vfp", "Mfp", "T")
COMPONENTES_ESFUERZO = ("N11", "N22", "N12", "M11", "M22", "M12")


@dataclass
class BaseMuro:
    """Lo que hace falta para sumar las fuerzas en la base de un muro."""

    area: str
    centro: np.ndarray
    ejes: tuple[np.ndarray, np.ndarray, np.ndarray]
    # (elemento, posición del nodo en el elemento 0..3)
    nodos: list[tuple[str, int]]
    longitud: float
    elevacion: float


def bases_muros(modelo: Edificio, malla: Malla) -> dict[str, BaseMuro]:
    out = {}
    for a in modelo.areas:
        if a.tipo != "muro":
            continue
        ids = malla.rejillas[a.id]
        n1, n2 = len(ids) - 1, len(ids[0]) - 1
        bordes = {
            "j0": [ids[i][0] for i in range(n1 + 1)],
            "i1": [ids[n1][j] for j in range(n2 + 1)],
            "j1": [ids[i][n2] for i in range(n1 + 1)],
            "i0": [ids[0][j] for j in range(n2 + 1)],
        }
        clave = min(bordes, key=lambda k: np.mean([malla.nodos[n][2] for n in bordes[k]]))
        en_base = set(bordes[clave])
        nodos = []
        for e in malla.elementos_de(a.id):
            for k, n in enumerate(e.nodos):
                if n in en_base:
                    nodos.append((e.id, k))
        extremos = [malla.nodos[bordes[clave][0]], malla.nodos[bordes[clave][-1]]]
        centro = (extremos[0] + extremos[1]) / 2
        out[a.id] = BaseMuro(
            area=a.id, centro=centro, ejes=modelo.ejes_area(a), nodos=nodos,
            longitud=float(np.linalg.norm(extremos[1] - extremos[0])), elevacion=float(centro[2]),
        )
    return out


def fuerzas_muro(base: BaseMuro, malla: Malla, fuerzas: dict[str, list[float]]) -> dict[str, float]:
    """P, V, M (en el plano) y Vfp, Mfp (fuera del plano), T (torsión) en la base del muro."""
    S = np.zeros(3)
    Mo = np.zeros(3)
    elementos = {e.id: e for e in malla.elementos_de(base.area)}
    for eid, k in base.nodos:
        f = np.asarray(fuerzas[eid][6 * k:6 * k + 6], dtype=float)
        p = malla.nodos[elementos[eid].nodos[k]]
        # Lo que el muro transmite al nodo es lo contrario de lo que el nodo le hace al muro
        S -= f[:3]
        Mo -= f[3:] + np.cross(p - base.centro, f[:3])
    e1, e2, e3 = base.ejes
    return {
        # Con compresión el muro empuja hacia abajo: S·e2 < 0, P < 0
        "P": float(S @ e2),
        "V": float(S @ e1),
        "M": float(-(Mo @ e3)),
        "Vfp": float(S @ e3),
        "Mfp": float(Mo @ e1),
        "T": float(Mo @ e2),
    }


def todas_fuerzas_muros(modelo: Edificio, malla: Malla, fuerzas: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    return {a: fuerzas_muro(b, malla, fuerzas) for a, b in bases_muros(modelo, malla).items()}


def esfuerzos_elemento(
    p: np.ndarray, u: np.ndarray, ejes, E: float, nu: float, t: float
) -> list[float]:
    """[N11, N22, N12, M11, M22, M12] en el centro de un cuadrilátero con nodos p (4, 3)
    y desplazamientos u (4, 6) globales."""
    e1, e2, e3 = ejes
    x = (p - p[0]) @ e1
    y = (p - p[0]) @ e2
    dxi = np.array([-1.0, 1.0, 1.0, -1.0]) / 4
    deta = np.array([-1.0, -1.0, 1.0, 1.0]) / 4
    J = np.array([[dxi @ x, dxi @ y], [deta @ x, deta @ y]])
    dN = np.linalg.solve(J, np.vstack([dxi, deta]))  # (2, 4): d/dx, d/dy
    u1, u2 = u[:, :3] @ e1, u[:, :3] @ e2
    t1, t2 = u[:, 3:] @ e1, u[:, 3:] @ e2
    ex, ey = dN[0] @ u1, dN[1] @ u2
    gxy = dN[1] @ u1 + dN[0] @ u2
    C = E * t / (1 - nu**2)
    N = [C * (ex + nu * ey), C * (ey + nu * ex), C * (1 - nu) / 2 * gxy]
    wxx = -(dN[0] @ t2)
    wyy = dN[1] @ t1
    wxy = (dN[0] @ t1 - dN[1] @ t2) / 2
    D = E * t**3 / (12 * (1 - nu**2))
    M = [D * (wxx + nu * wyy), D * (wyy + nu * wxx), D * (1 - nu) * wxy]
    return [float(v) for v in (*N, *M)]


def esfuerzos_areas(modelo: Edificio, malla: Malla, desplazamientos: dict[str, list[float]]) -> dict[str, dict[str, list[float]]]:
    """área -> elemento -> [N11, N22, N12, M11, M22, M12] en el centro del elemento."""
    out: dict[str, dict[str, list[float]]] = {}
    for a in modelo.areas:
        s = modelo.seccion_area(a.seccion)
        mat = modelo.material(s.material)
        ejes = modelo.ejes_area(a)
        tabla = out.setdefault(a.id, {})
        for e in malla.elementos_de(a.id):
            p = np.array([malla.nodos[n] for n in e.nodos])
            u = np.array([desplazamientos[n] for n in e.nodos], dtype=float)
            tabla[e.id] = esfuerzos_elemento(p, u, ejes, mat.E * s.mod_rigidez, mat.nu, s.espesor)
    return out


def extremos_esfuerzos(esfuerzos: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    """componente -> (mínimo, máximo) entre los elementos de un área."""
    arr = np.array(list(esfuerzos.values())).reshape(-1, 6)
    return {c: (float(arr[:, k].min()), float(arr[:, k].max())) for k, c in enumerate(COMPONENTES_ESFUERZO)}
