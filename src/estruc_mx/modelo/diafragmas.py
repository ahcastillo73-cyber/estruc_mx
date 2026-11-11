"""Diafragmas rígidos: nodos de cada piso, nodo maestro y centro de masa.

Lo usan los dos motores (PyNite y OpenSees) a partir de la misma malla:

- Los esclavos son todos los nodos de la malla de análisis a la elevación del diafragma
  (incluidos los nodos generados en losas y muros), salvo los que tienen restringido UX, UY o RZ.
- El nodo maestro está en el centro de masa del piso, calculado con las masas nodales de
  `modelo/masas.py` (las mismas del análisis modal). Si el piso no tiene masa, se usa el
  centroide de los nodos esclavos.
- El maestro solo tiene libres UX, UY y RZ; la masa se queda en los esclavos, así que la inercia
  rotacional del piso sale sola de cómo está repartida.

OpenSees lo aplica exacto con `rigidDiaphragm`; PyNite, que no tiene restricciones de este tipo,
con barras muy rígidas en el plano del piso (ver motores/pynite.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .edificio import Edificio
    from .malla import Malla

TOLERANCIA = 1e-6  # m


@dataclass
class DiafragmaMalla:
    nombre: str
    z: float
    maestro: str  # id del nodo maestro (no está en Malla.nodos; lo agrega cada motor)
    centro: np.ndarray  # (x, y, z) del centro de masa
    masa: float  # t, suma de las masas de los esclavos
    esclavos: list[str] = field(default_factory=list)
    con_masa: bool = True  # False si el centro es el centroide geométrico


def diafragmas_de_malla(modelo: "Edificio", malla: "Malla") -> list[DiafragmaMalla]:
    """Diafragmas del modelo sobre la malla; los que tienen menos de dos nodos se omiten con aviso."""
    if not modelo.diafragmas:
        return []
    from .masas import masas_nodales

    try:
        masas = masas_nodales(modelo, malla)
    except ValueError:
        masas = {}
    ids = list(malla.nodos)
    P = np.array([malla.nodos[n] for n in ids], dtype=float).reshape(-1, 3)
    out: list[DiafragmaMalla] = []
    for d in modelo.diafragmas:
        esclavos = [
            ids[k] for k in np.nonzero(np.abs(P[:, 2] - d.z) < 10 * TOLERANCIA)[0]
            if not _restringido(malla.apoyos.get(ids[k]))
        ]
        if len(esclavos) < 2:
            malla.avisos.append(f"Diafragma {d.nombre}: no hay al menos dos nodos libres a z = {d.z:g} m; no se aplica.")
            continue
        xy = np.array([malla.nodos[n][:2] for n in esclavos])
        m = np.array([masas.get(n, 0.0) for n in esclavos])
        con_masa = bool(m.sum() > 0)
        c = (m @ xy) / m.sum() if con_masa else xy.mean(axis=0)
        maestro = f"{d.nombre}:CM"
        while maestro in malla.nodos:
            maestro += "'"
        out.append(DiafragmaMalla(
            nombre=d.nombre, z=d.z, maestro=maestro, centro=np.array([c[0], c[1], d.z]),
            masa=float(m.sum()), esclavos=esclavos, con_masa=con_masa,
        ))
    return out


def _restringido(r) -> bool:
    return r is not None and (r[0] or r[1] or r[5])


def centros_de_masa(modelo: "Edificio", malla: "Malla | None" = None) -> dict[str, tuple[float, float, float, float]]:
    """Diafragma -> (x, y, z, masa en t) del centro de masa de cada piso con diafragma."""
    from .malla import discretizar

    malla = malla or discretizar(modelo)
    return {d.nombre: (float(d.centro[0]), float(d.centro[1]), d.z, d.masa) for d in malla.diafragmas}
