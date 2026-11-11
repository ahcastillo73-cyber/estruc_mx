"""Valores de la Norma Técnica Complementaria para Diseño por Sismo (CDMX, 2023) que usa el programa.

Verificados contra el texto de la edición 2023 (secciones 1.7, 2.3, 2.5, 3.1, 4.3 y 7.5).

Distorsiones (1.7):
- Seguridad de Vida: distorsión con el espectro de diseño (reducido por Q′R′) multiplicada por
  Q·R′, contra γSV.
- Ocupación Inmediata (Grupo A): distorsión con el espectro elástico, contra γOI.
- Limitación de Daño No Estructural (Grupo B): distorsión con el espectro elástico de la
  intensidad base de diseño multiplicado por Ks (3.1.1), contra 0.002 o 0.004.
"""

from __future__ import annotations

# clave -> (descripción, Q, γSV, γOI); tablas 4.3.1, 4.3.2 y 4.3.3 de la edición 2023.
# No se aplica el incremento de 0.005 para muros esbeltos (nota [4] de la tabla 4.3.1) ni la
# reducción para mampostería de más de 6 niveles (nota [1] de la tabla 4.3.3).
DISTORSIONES_LIMITE: dict[str, tuple[str, float, float, float | None]] = {
    "marco_concreto_alta": ("Marcos de concreto de ductilidad alta", 4.0, 0.030, 0.0075),
    "marco_concreto_media": ("Marcos de concreto de ductilidad media", 3.0, 0.020, 0.0075),
    "marco_concreto_baja": ("Marcos de concreto de ductilidad baja", 2.0, 0.015, 0.0075),
    "dual_concreto_alta": ("Sistema dual de marcos y muros de concreto de ductilidad alta", 4.0, 0.020, 0.0050),
    "dual_concreto_media": ("Sistema dual de marcos y muros de concreto de ductilidad media", 3.0, 0.015, 0.0050),
    "dual_concreto_baja": ("Sistema dual de marcos y muros de concreto de ductilidad baja", 2.0, 0.010, 0.0050),
    "muros_concreto_alta": ("Muros de concreto de ductilidad alta", 4.0, 0.020, 0.0050),
    "muros_concreto_media": ("Muros de concreto de ductilidad media", 3.0, 0.015, 0.0050),
    "muros_concreto_baja": ("Muros de concreto de ductilidad baja", 2.0, 0.010, 0.0050),
    "marcos_muros_diafragma_alta": ("Marcos de ductilidad alta con muros diafragma no desligados", 4.0, 0.020, 0.0050),
    "marcos_muros_diafragma_media": ("Marcos de ductilidad media con muros diafragma no desligados", 3.0, 0.015, 0.0050),
    "marcos_muros_diafragma_baja": ("Marcos de ductilidad baja con muros diafragma no desligados", 2.0, 0.010, 0.0050),
    "losa_plana": ("Columnas de concreto interconectadas con losas planas", 1.0, 0.005, 0.0020),
    "marco_acero_alta": ("Marcos de acero de ductilidad alta", 4.0, 0.030, 0.0075),
    "marco_acero_media": ("Marcos de acero de ductilidad media", 3.0, 0.020, 0.0075),
    "marco_acero_baja": ("Marcos de acero de ductilidad baja", 2.0, 0.015, 0.0075),
    "contraviento_excentrico": ("Marcos de acero con contraventeos excéntricos", 4.0, 0.020, 0.0050),
    "contraviento_concentrico_alta": ("Marcos de acero con contraventeos concéntricos de ductilidad alta", 3.0, 0.015, 0.0050),
    "contraviento_concentrico_media": ("Marcos de acero con contraventeos concéntricos de ductilidad media", 2.0, 0.010, 0.0050),
    "contraviento_tension": ("Marcos de acero con contraventeos concéntricos que trabajan solo en tensión", 1.0, 0.005, 0.0030),
    "mamposteria_confinada_maciza_refuerzo": (
        "Mampostería confinada de piezas macizas con refuerzo horizontal", 2.0, 0.010, 0.0015),
    "mamposteria_confinada": ("Mampostería confinada de piezas macizas", 2.0, 0.005, 0.0015),
    "mamposteria_confinada_hueca_refuerzo": (
        "Mampostería confinada de piezas huecas con refuerzo horizontal", 2.0, 0.008, 0.0015),
    "mamposteria_confinada_hueca": ("Mampostería confinada de piezas huecas", 1.5, 0.004, 0.0015),
    "mamposteria_refuerzo_interior": ("Mampostería de piezas huecas reforzadas interiormente", 1.5, 0.006, None),
    "mamposteria_no_reforzada": (
        "Mampostería de piezas huecas o macizas no confinada ni reforzada (solo estructuras existentes)", 1.0, 0.0015, None),
    "mamposteria_piedra": ("Mampostería de piedras naturales", 1.0, 0.0015, None),
}

MASA_PARTICIPANTE_MINIMA = 0.90  # fracción de la masa total en cada dirección

# 7.5: si el cortante basal del análisis modal es menor que a_min·W, se escalan las fuerzas de
# diseño (no los desplazamientos). a_min = 0.04/R′ si Ts < 0.5 s, 0.06/R′ si Ts ≥ 1.0 s,
# interpolado entre ambos; Ts = periodo dominante más largo del terreno.
AMIN_TS_CORTO = (0.5, 0.04)
AMIN_TS_LARGO = (1.0, 0.06)


def a_min(Ts: float | None, R: float = 1.0) -> float:
    """Coeficiente de cortante basal mínimo (fracción de W). Sin Ts se toma el mayor."""
    (t1, a1), (t2, a2) = AMIN_TS_CORTO, AMIN_TS_LARGO
    if Ts is None or Ts >= t2:
        a = a2
    elif Ts <= t1:
        a = a1
    else:
        a = a1 + (a2 - a1) * (Ts - t1) / (t2 - t1)
    return a / R


def excentricidad_accidental(i: int, n: int) -> float:
    """Ec. 2.3.2: e_a,i = [0.05 + 0.05·(i − 1)/(n − 1)]·b_i, como fracción de b_i (i = 1 abajo)."""
    return 0.05 + (0.05 * (i - 1) / (n - 1) if n > 1 else 0.0)


def ks(zona: str, Ts: float | None = None) -> float:
    """Ec. 3.1.1: factor que lleva el espectro elástico de la intensidad base de diseño a la
    frecuente, para Limitación de Daño. Zona A 1/6, B 1/[6 − 4(Ts − 0.5)], C 1/4."""
    zona = zona.upper()
    if zona == "A":
        return 1 / 6
    if zona == "C":
        return 1 / 4
    if zona == "B":
        if Ts is None:
            raise ValueError("para la zona B hace falta Ts")
        Ts = min(max(Ts, 0.5), 1.0)  # la expresión va de 1/6 (Ts = 0.5 s) a 1/4 (Ts = 1 s)
        return 1 / (6 - 4 * (Ts - 0.5))
    raise ValueError(f"zona '{zona}' desconocida; opciones: A, B, C")


# 2.5: 100 % de los efectos del componente en una dirección más 30 % del perpendicular, con los
# signos más desfavorables.
FACTOR_ORTOGONAL = 0.30

# 1.7: Limitación de Daño No Estructural ≤ 0.002, o 0.004 si los elementos no estructurales
# soportan deformaciones apreciables o están separados de la estructura.
DISTORSION_SERVICIO = 0.002
DISTORSION_SERVICIO_SEPARADOS = 0.004
