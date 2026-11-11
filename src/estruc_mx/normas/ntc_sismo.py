"""Valores de las NTC para Diseño por Sismo (CDMX) que usa el programa.

Las distorsiones límite son las de la tabla de distorsiones permisibles para seguridad
contra colapso de las NTC Sismo 2017, que la edición 2023 conserva según lo revisado hasta
ahora. Verificar contra la edición vigente antes de usarlas en un proyecto.

Según las NTC, la distorsión que se compara es la calculada con el espectro reducido
multiplicada por Q·R. Aquí ese factor es por defecto `espectro.reduccion`; si el espectro
es elástico (reducción 1), la distorsión ya está sin reducir.
"""

from __future__ import annotations

# clave -> (descripción, distorsión límite)
DISTORSIONES_LIMITE: dict[str, tuple[str, float]] = {
    "marco_ductil_concreto": ("Marcos dúctiles de concreto reforzado (Q = 3 o 4)", 0.030),
    "marco_ductil_acero": ("Marcos dúctiles de acero (Q = 3 o 4)", 0.030),
    "marco_concreto_limitado": ("Marcos de concreto reforzado con ductilidad limitada (Q = 1 o 2)", 0.015),
    "marco_acero_limitado": ("Marcos de acero con ductilidad limitada (Q = 1 o 2)", 0.015),
    "losa_plana": ("Losas planas sin muros o contravientos", 0.015),
    "contraviento_excentrico": ("Marcos de acero con contravientos excéntricos", 0.020),
    "contraviento_concentrico": ("Marcos de acero o concreto con contravientos concéntricos", 0.015),
    "muros_marco_ductil": ("Muros combinados con marcos dúctiles de concreto (Q = 3)", 0.015),
    "muros_marco_limitado": ("Muros combinados con marcos de concreto con ductilidad limitada (Q = 1 o 2)", 0.010),
    "muros_diafragma": ("Muros diafragma", 0.006),
    "mamposteria_confinada_reforzada": (
        "Mampostería confinada de piezas macizas con refuerzo horizontal o malla", 0.005),
    "mamposteria_confinada": (
        "Mampostería confinada de piezas macizas, o de piezas huecas confinada y reforzada", 0.004),
    "mamposteria_refuerzo_interior": ("Mampostería de piezas huecas con refuerzo interior", 0.002),
    "mamposteria_no_reforzada": (
        "Mampostería que no cumple las especificaciones de confinada ni de reforzada", 0.0015),
}

MASA_PARTICIPANTE_MINIMA = 0.90  # fracción de la masa total en cada dirección

# --- Revisión sísmica ----------------------------------------------------------------
# Lo que sigue se verificó contra el texto de las NTC Sismo 2020 (Gaceta Oficial de la CDMX,
# 9 de junio de 2020); no se pudo consultar completa la edición 2023, que puede haber
# cambiado valores. Lo marcado «de memoria» no se pudo confirmar en ninguna de las dos.

# Sección 1.7 (2020): si el cortante basal del análisis modal es menor que a_min·W, se
# escalan las fuerzas de diseño (no los desplazamientos). a_min = 0.04/R si Ts < 0.5 s,
# 0.06/R si Ts ≥ 1.0 s, interpolado entre ambos; Ts = periodo dominante más largo del terreno.
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
    """Fracción de la dimensión en planta b del piso i (1 = el más bajo) de n pisos.

    De memoria: e_a,i = [0.05 + 0.05·(i − 1)/(n − 1)]·b_i (0.05b abajo, 0.10b arriba). La
    ecuación 2.2.3 de 2020 existe con esta forma (b_i y n) pero no se pudo leer el texto."""
    return 0.05 + (0.05 * (i - 1) / (n - 1) if n > 1 else 0.0)


# Sección 2.4 (2020): 100 % de los efectos del componente en una dirección más 30 % del
# perpendicular, con los signos más desfavorables.
FACTOR_ORTOGONAL = 0.30

# Sección 1.8 b (2020): distorsión de servicio (limitación de daños) ≤ 0.002, o 0.004 si los
# elementos no estructurales soportan deformaciones apreciables o están separados.
DISTORSION_SERVICIO = 0.002
DISTORSION_SERVICIO_SEPARADOS = 0.004
