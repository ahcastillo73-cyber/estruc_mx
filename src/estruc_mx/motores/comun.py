from __future__ import annotations

from ..modelo import Combinacion, Edificio


def combinaciones_efectivas(modelo: Edificio) -> list[Combinacion]:
    """Las combinaciones del modelo; si no hay, una por patrón con factor 1."""
    if modelo.combinaciones:
        return list(modelo.combinaciones)
    return [Combinacion(nombre=p.nombre, factores={p.nombre: 1.0}) for p in modelo.patrones]
