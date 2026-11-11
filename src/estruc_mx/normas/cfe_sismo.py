"""Valores del Manual de Diseño de Obras Civiles de CFE, Diseño por Sismo (MDOC 2015).

TODO lo de este archivo se tomó de memoria y no se ha verificado contra el manual.
"""

from __future__ import annotations

# Cortante basal mínimo del análisis dinámico: 0.8 del cortante estático, a(T)·W/(Q'R) con
# el periodo fundamental de la dirección.
FACTOR_CORTANTE_MINIMO = 0.8

# Excentricidad accidental constante en todos los pisos, fracción de b.
EXCENTRICIDAD_ACCIDENTAL = 0.05


def excentricidad_accidental(i: int, n: int) -> float:
    return EXCENTRICIDAD_ACCIDENTAL
