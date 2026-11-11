"""Niveles de piso, centros de masa y dimensiones en planta, a partir de la geometría.

El modelo no declara pisos: un nivel es cada elevación distinta de los nodos del modelo por
encima de la base (la elevación más baja con apoyos). Los nodos de la malla de muros y losas
que quedan entre dos niveles se asignan al más cercano; así la masa del muro se reparte entre
el piso de abajo y el de arriba, como en un modelo de masas concentradas por piso.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..modelo import Edificio
from ..modelo.malla import Malla

_DEC = 6


@dataclass
class Piso:
    z: float  # elevación del nivel, m
    nodos: list[str]  # nodos de la malla asignados al nivel
    masa: float  # t
    xc: float  # centro de masa, m
    yc: float
    bx: float  # dimensión en planta en X, m
    by: float  # dimensión en planta en Y, m


def niveles(modelo: Edificio) -> list[float]:
    """Elevaciones de los niveles de piso por encima de la base, de abajo hacia arriba."""
    zs = sorted({round(n.z, _DEC) for n in modelo.nodos})
    if not zs:
        return []
    apoyados = [round(modelo.nodo(a.nodo).z, _DEC) for a in modelo.apoyos]
    base = min(apoyados) if apoyados else zs[0]
    return [z for z in zs if z > base]


def asignar(malla: Malla, zs: list[float]) -> dict[str, int]:
    """Nodo de la malla -> índice del nivel más cercano; los de la base o más abajo no aparecen."""
    if not zs:
        return {}
    base = zs[0] - (zs[1] - zs[0] if len(zs) > 1 else zs[0])
    arr = np.array(zs)
    out: dict[str, int] = {}
    for n, p in malla.nodos.items():
        z = float(p[2])
        k = int(np.argmin(np.abs(arr - z)))
        # Más cerca de la base que del primer nivel: es parte de la base
        if k == 0 and abs(z - base) < abs(z - zs[0]):
            continue
        out[n] = k
    return out


def pisos(modelo: Edificio, malla: Malla, masas: dict[str, float]) -> list[Piso]:
    """Un `Piso` por nivel, con su masa, centro de masa y dimensiones en planta.

    Las dimensiones salen de los nodos del modelo que están exactamente en el nivel (sus
    columnas, muros y losas); si no hay ninguno, de todos los nodos asignados."""
    zs = niveles(modelo)
    nivel = asignar(malla, zs)
    out = []
    for k, z in enumerate(zs):
        nodos = [n for n, i in nivel.items() if i == k]
        m = np.array([masas.get(n, 0.0) for n in nodos])
        xy = np.array([malla.nodos[n][:2] for n in nodos]) if nodos else np.zeros((0, 2))
        en_nivel = [malla.nodos[n][:2] for n in nodos if abs(malla.nodos[n][2] - z) < 1e-6]
        ext = np.array(en_nivel) if en_nivel else xy
        mt = float(m.sum())
        if mt > 0:
            xc, yc = (m @ xy) / mt
        elif len(xy):
            xc, yc = xy.mean(axis=0)
        else:
            xc = yc = 0.0
        bx, by = (ext.max(axis=0) - ext.min(axis=0)) if len(ext) else (0.0, 0.0)
        out.append(Piso(z=z, nodos=nodos, masa=mt, xc=float(xc), yc=float(yc), bx=float(bx), by=float(by)))
    return out
