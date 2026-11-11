"""Masas concentradas en los nodos, iguales para todos los motores.

La masa se obtiene de las cargas verticales de los patrones indicados en
`Edificio.fuente_masa` (factor por patrón), más el peso propio de las barras si
`peso_propio_en_masa` es verdadero, más las masas nodales explícitas.
Las cargas distribuidas y el peso propio se reparten mitad y mitad a los extremos.
Solo se considera masa traslacional (igual en X, Y y Z).
"""

from __future__ import annotations

from .edificio import Edificio

G = 9.80665  # m/s²


def masas_nodales(modelo: Edificio) -> dict[str, float]:
    """Masa (t = kN·s²/m) por nodo; solo aparecen los nodos con masa."""
    m: dict[str, float] = {}

    def sumar(nodo: str, peso_kN: float) -> None:
        if peso_kN:
            m[nodo] = m.get(nodo, 0.0) + peso_kN / G

    f = modelo.fuente_masa
    for c in modelo.cargas_nodales:
        if c.patron in f:
            sumar(c.nodo, -c.fuerzas[2] * f[c.patron])
    for c in modelo.cargas_distribuidas:
        if c.patron in f and c.direccion == "Z":
            b = modelo.barra(c.barra)
            mitad = -c.w * modelo.longitud(b) * f[c.patron] / 2.0
            sumar(b.i, mitad)
            sumar(b.j, mitad)
    if modelo.peso_propio_en_masa:
        for b in modelo.barras:
            s = modelo.seccion(b.seccion)
            mitad = modelo.material(s.material).peso_vol * s.A * modelo.longitud(b) / 2.0
            sumar(b.i, mitad)
            sumar(b.j, mitad)
    for mn in modelo.masas_nodales:
        m[mn.nodo] = m.get(mn.nodo, 0.0) + mn.masa

    apoyados = {a.nodo for a in modelo.apoyos if all(a.restricciones[:3])}
    negativas = [n for n, v in m.items() if v < 0 and n not in apoyados]
    if negativas:
        raise ValueError(f"masa negativa en nodos {negativas}: revisa el signo de las cargas en fuente_masa")
    return {n: v for n, v in m.items() if v > 0}
