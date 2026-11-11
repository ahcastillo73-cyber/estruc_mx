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
