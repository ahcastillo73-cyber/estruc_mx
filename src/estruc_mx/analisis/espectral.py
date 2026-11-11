"""Propiedades modales y análisis modal espectral, independientes del motor.

Trabaja con las formas modales de cualquier motor (`Modos`) y con las masas nodales
de `modelo/masas.py`, de modo que PyNite y OpenSees se tratan igual.
Unidades: t, kN, m, s. Las ordenadas espectrales están en g.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ..modelo import Edificio, masas_nodales
from ..modelo.masas import G
from ..motores import Modos

_GDL = {"X": 0, "Y": 1, "Z": 2}


@dataclass
class PropiedadesModales:
    periodos: list[float]
    masa_total: float
    # dirección -> lista por modo
    participacion: dict[str, list[float]] = field(default_factory=dict)
    masa_efectiva: dict[str, list[float]] = field(default_factory=dict)  # t
    fraccion_masa: dict[str, list[float]] = field(default_factory=dict)  # de la masa total

    def fraccion_acumulada(self, direccion: str) -> list[float]:
        return list(np.cumsum(self.fraccion_masa[direccion]))


def propiedades_modales(modelo: Edificio, modos: Modos) -> PropiedadesModales:
    masas = masas_nodales(modelo)
    mtot = sum(masas.values())
    prop = PropiedadesModales(periodos=list(modos.periodos), masa_total=mtot)
    for d, g in _GDL.items():
        prop.participacion[d], prop.masa_efectiva[d], prop.fraccion_masa[d] = [], [], []
    for forma in modos.formas:
        Mn = sum(m * sum(forma[n][k] ** 2 for k in range(3)) for n, m in masas.items())
        for d, g in _GDL.items():
            Ln = sum(m * forma[n][g] for n, m in masas.items())
            gamma = Ln / Mn if Mn > 0 else 0.0
            meff = Ln * gamma
            prop.participacion[d].append(gamma)
            prop.masa_efectiva[d].append(meff)
            prop.fraccion_masa[d].append(meff / mtot if mtot > 0 else 0.0)
    return prop


def coeficientes_cqc(periodos: list[float], amortiguamiento: float = 0.05) -> np.ndarray:
    """Coeficientes de correlación modal de Der Kiureghian para amortiguamiento igual."""
    w = np.array([2 * math.pi / T for T in periodos])
    z = amortiguamiento
    r = w[None, :] / w[:, None]
    return 8 * z**2 * (1 + r) * r**1.5 / ((1 - r**2) ** 2 + 4 * z**2 * r * (1 + r) ** 2)


def _combinar(valores: np.ndarray, rho: np.ndarray | None) -> np.ndarray:
    """valores: (modos, ...) -> combinación SRSS (rho=None) o CQC sobre el eje 0."""
    if rho is None:
        return np.sqrt(np.sum(valores**2, axis=0))
    v = valores.reshape(valores.shape[0], -1)
    return np.sqrt(np.maximum(np.einsum("i...,ij,j...->...", v, rho, v), 0.0)).reshape(valores.shape[1:])


@dataclass
class Deriva:
    nivel: float  # elevación del extremo superior, m
    deriva: float  # desplazamiento relativo / altura
    barra: str


@dataclass
class RespuestaEspectral:
    direccion: str
    metodo: str
    propiedades: PropiedadesModales
    sa: list[float]  # g, por modo
    desplazamientos: dict[str, list[float]]  # nodo -> [UX..RZ], valores combinados (positivos)
    cortante_basal: float  # kN
    cortante_basal_modal: list[float]
    derivas: list[Deriva]  # la máxima por nivel, de abajo hacia arriba


def espectral(
    modelo: Edificio,
    modos: Modos,
    direccion: Literal["X", "Y"] = "X",
    metodo: Literal["CQC", "SRSS"] = "CQC",
    espectro=None,
    amortiguamiento: float = 0.05,
) -> RespuestaEspectral:
    espectro = espectro or modelo.espectro
    if espectro is None:
        raise ValueError("el modelo no tiene espectro definido")
    prop = propiedades_modales(modelo, modos)
    validos = [i for i, T in enumerate(modos.periodos) if math.isfinite(T) and T > 0]
    T = [modos.periodos[i] for i in validos]
    gamma = [prop.participacion[direccion][i] for i in validos]
    sa = [espectro.sa(t) for t in T]

    # Desplazamiento modal: Γ · Sa·g / ω²
    amp = np.array([g * s * G / (2 * math.pi / t) ** 2 for g, s, t in zip(gamma, sa, T)])
    nodos = [n.id for n in modelo.nodos]
    phi = np.array([[modos.formas[i][n] for n in nodos] for i in validos])  # (modos, nodos, 6)
    u_modal = phi * amp[:, None, None]
    rho = coeficientes_cqc(T, amortiguamiento) if metodo == "CQC" else None
    u = _combinar(u_modal, rho)

    V_modal = np.array([prop.masa_efectiva[direccion][i] * s * G for i, s in zip(validos, sa)])
    V = float(_combinar(V_modal[:, None], rho)[0])

    g = _GDL[direccion]
    por_nivel: dict[float, Deriva] = {}
    indice = {n: k for k, n in enumerate(nodos)}
    for b in modelo.barras:
        if b.tipo != "columna":
            continue
        ni, nj = modelo.nodo(b.i), modelo.nodo(b.j)
        abajo, arriba = (ni, nj) if nj.z > ni.z else (nj, ni)
        h = arriba.z - abajo.z
        if h <= 0:
            continue
        rel = (u_modal[:, indice[arriba.id], g] - u_modal[:, indice[abajo.id], g]) / h
        valor = float(_combinar(rel[:, None], rho)[0])
        nivel = round(arriba.z, 6)
        if nivel not in por_nivel or valor > por_nivel[nivel].deriva:
            por_nivel[nivel] = Deriva(nivel=nivel, deriva=valor, barra=b.id)

    return RespuestaEspectral(
        direccion=direccion,
        metodo=metodo,
        propiedades=prop,
        sa=sa,
        desplazamientos={n: [float(v) for v in u[k]] for k, n in enumerate(nodos)},
        cortante_basal=V,
        cortante_basal_modal=[float(v) for v in V_modal],
        derivas=[por_nivel[z] for z in sorted(por_nivel)],
    )
