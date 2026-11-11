"""Masas concentradas en los nodos, iguales para todos los motores.

La masa se obtiene de las cargas verticales de los patrones indicados en
`Edificio.fuente_masa` (factor por patrón), más el peso propio de las barras si
`peso_propio_en_masa` es verdadero (barras, muros y losas), más las masas nodales explícitas.
Si `peso_propio_en_masa` es falso, el peso propio entra solo por los patrones de la fuente de
masa que lo aplican (`PatronCarga.peso_propio`); así nunca se cuenta dos veces.
Las cargas distribuidas y el peso propio de las barras se reparten mitad y mitad a los extremos
de cada tramo; las cargas por m² y el peso de muros y losas, a los nodos de su malla.
Solo se considera masa traslacional (igual en X, Y y Z).
"""

from __future__ import annotations

import numpy as np

from .edificio import Edificio
from .malla import Malla, discretizar

G = 9.80665  # m/s²


def masas_nodales(modelo: Edificio, malla: Malla | None = None) -> dict[str, float]:
    """Masa (t = kN·s²/m) por nodo de la malla de análisis; solo aparecen los nodos con masa."""
    malla = malla or discretizar(modelo)
    m: dict[str, float] = {}

    def sumar(nodo: str, peso_kN: float) -> None:
        if peso_kN:
            m[nodo] = m.get(nodo, 0.0) + peso_kN / G

    def largo(seg) -> float:
        return float(np.linalg.norm(malla.nodos[seg.j] - malla.nodos[seg.i]))

    f = modelo.fuente_masa
    for c in modelo.cargas_nodales:
        if c.patron in f:
            sumar(c.nodo, -c.fuerzas[2] * f[c.patron])
    for c in modelo.cargas_distribuidas:
        if c.patron in f and c.direccion == "Z":
            for seg in malla.segmentos_de(c.barra):
                mitad = -c.w * largo(seg) * f[c.patron] / 2.0
                sumar(seg.i, mitad)
                sumar(seg.j, mitad)
    for patron, tabla in malla.cargas_area.items():
        if patron in f:
            for nodo, F in tabla.items():
                sumar(nodo, -F[2] * f[patron])
    # El peso propio cuenta una vez: con `peso_propio_en_masa`, completo; si no, en la medida
    # en que lo incluyan los patrones de la fuente de masa.
    if modelo.peso_propio_en_masa:
        factor_pp = 1.0
    else:
        factor_pp = sum(f[p.nombre] * p.peso_propio for p in modelo.patrones if p.nombre in f)
    if factor_pp:
        for nodo, peso in pesos_propios(modelo, malla).items():
            sumar(nodo, factor_pp * peso)
    for mn in modelo.masas_nodales:
        m[mn.nodo] = m.get(mn.nodo, 0.0) + mn.masa

    apoyados = {n for n, r in malla.apoyos.items() if all(r[:3])}
    negativas = [n for n, v in m.items() if v < 0 and n not in apoyados]
    if negativas:
        raise ValueError(f"masa negativa en nodos {negativas}: revisa el signo de las cargas en fuente_masa")
    return {n: v for n, v in m.items() if v > 0}


def pesos_propios(modelo: Edificio, malla: Malla) -> dict[str, float]:
    """Peso propio (kN) de barras, muros y losas concentrado en los nodos de la malla."""
    w: dict[str, float] = dict(malla.peso_areas)
    for seg in malla.segmentos:
        mitad = peso_lineal(modelo, seg.barra) * float(np.linalg.norm(malla.nodos[seg.j] - malla.nodos[seg.i])) / 2.0
        for n in (seg.i, seg.j):
            w[n] = w.get(n, 0.0) + mitad
    return {n: v for n, v in w.items() if v}


def peso_lineal(modelo: Edificio, barra: str) -> float:
    """Peso por metro (kN/m) de una barra."""
    s = modelo.seccion(modelo.barra(barra).seccion)
    return modelo.material(s.material).peso_vol * s.A
