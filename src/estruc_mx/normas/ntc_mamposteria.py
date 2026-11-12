"""Valores de la Norma Técnica Complementaria para Diseño y Construcción de Estructuras de
Mampostería (CDMX, 2023) que usa el programa.

Verificados contra el texto de la edición 2023 incluido en el PDF de las NTC 2023 (capítulos 2,
3, 4, 6, 7 y 12). Los esfuerzos se dan en MPa, como en la norma; el programa trabaja en kPa.
"""

from __future__ import annotations

import numpy as np

# --- 4.1.6 Factores de resistencia ----------------------------------------------------
FR_COMPRESION = 0.6  # 4.1.6.2, muros confinados, reforzados interiormente y diagonal de muros diafragma
FR_CORTANTE = 0.7  # 4.1.6.4
FR_FLEXION_BAJA_CARGA = 0.8  # 4.1.6.3.1 b), método optativo, Pu ≤ PR/3
FR_FLEXION_ALTA_CARGA = 0.6  # 4.1.6.3.1 b), Pu > PR/3

# --- 3.1.2.3 Factor de reducción por excentricidad y esbeltez -------------------------
FE_INTERIOR = 0.7
FE_EXTREMO = 0.6
ESBELTEZ_FE_SIMPLIFICADO = 20  # H/t máximo para usar FE = 0.7 o 0.6
K_ALTURA_EXTREMO = 1.0  # muros extremos en que se apoyan losas
K_ALTURA_INTERIOR = 0.8  # muros limitados por dos losas continuas
K_ALTURA_LIBRE = 2.0  # sin restricción lateral arriba


def fe_ecuacion(e_prima: float, t: float, k: float, H: float) -> float:
    """Ec. 3.1.2.3.1: FE = (1 − 2e′/t)·[1 − (kH/(30t))²]."""
    return max(0.0, (1 - 2 * e_prima / t) * (1 - (k * H / (30 * t)) ** 2))


def excentricidad_extremo(t: float, b: float) -> float:
    """Ec. 3.1.2.2.2: ec = t/2 − b/3, con b la longitud de apoyo de la losa."""
    return max(0.0, t / 2 - b / 3)


# --- 6.5.2 y 7.4.2 Cortante resistido por la mampostería --------------------------------
def factor_f(H_L: float) -> float:
    """Ec. 6.5.2.4: 1.5 si H/L ≤ 0.2, 1.0 si H/L ≥ 1.0, interpolado entre ambos."""
    return float(np.interp(H_L, [0.2, 1.0], [1.5, 1.0]))


LIMITE_VMR = 1.5  # VmR ≤ 1.5·FR·v'm·AT·f
SIGMA_MAX_ENTREPISO = 10 / 3  # 4.1.12.1: σi ≤ 3.33·v'm
VM_REFUERZO_HORIZONTAL = 1.0  # MPa, 6.5.2.2: con v'm ≥ 1 MPa el muro lleva refuerzo horizontal


# --- 6.5.3 y 7.4.3 Refuerzo horizontal -----------------------------------------------------
def k0(H_L: float) -> float:
    """Ec. 6.5.3.4.1.e: 1.3 si H/L ≤ 1.0, 1.0 si H/L ≥ 1.5, interpolado."""
    return float(np.interp(H_L, [1.0, 1.5], [1.3, 1.0]))


ALFA = 0.45  # 1/MPa, ec. 6.5.3.4.1.f


def eta_s(fm_mpa: float) -> float:
    """Ec. 6.5.3.4.1.g: 0.55 si f'm ≤ 6 MPa, 0.75 si f'm ≥ 9 MPa, interpolado."""
    return float(np.interp(fm_mpa, [6.0, 9.0], [0.55, 0.75]))


PH_FYH_MIN = 0.3  # MPa, 6.5.3.3.1 y 7.4.3.4.1
PH_FYH_MAX = 0.15  # × f'm·fan, 6.5.3.3.2 (no menor que PH_FYH_MIN)
PH_FYH_EFECTIVO = 0.1  # × f'm·fan, ec. 6.5.3.4.1.c: (ph·fyh)e
FYH_MAX = 600.0  # MPa, 6.5.3.1.3
SH_MAX = 0.45  # m, 6.5.3.2.1 (ni seis hiladas)
ASH_JUNTA = 0.05  # Ash ≤ 0.05·hj·t, 6.5.3.3.2
PHFYH_PVFYV_MIN = 0.84  # MPa, 7.1.5.1.a, muros reforzados interiormente


# --- 6.1 y 6.2 Requisitos de mampostería confinada ----------------------------------------
ESPESOR_MIN = 0.12  # m, 6.1.3 y 7.1.2 (estructuras Tipo I)
ESBELTEZ_MAX = 25  # H/t, 6.1.3 y 7.1.2
CASTILLO_B_MIN = 0.12  # m, 6.2.1.1 b), perpendicular al muro
CASTILLO_H_MIN = 0.15  # m, paralela al muro
SEP_CASTILLOS_ALTURA = 1.5  # × H, 6.2.1.1 a)
SEP_CASTILLOS_MAX = 4.0  # m
DALA_B_MIN = 0.12  # m, 6.2.1.2 b)
DALA_H_MIN = 0.15  # m (o el peralte de una losa de 10 cm o más)
SEP_DALAS_MAX = 3.0  # m, 6.2.1.2 a)
FC_CASTILLOS_MIN = 20.0  # MPa, 6.2.1.3.1
BARRAS_CASTILLO_MIN = 4  # 6.2.2.2
ESTRIBO_S_MAX = 0.20  # m, 6.2.2.3 (y 1.5·t)
HO_MIN = 0.40  # m, 6.2.3.2: Ho = max(H/6, 400 mm), estribos a hc/2


def as_min_castillo(fc: float, fy: float, bc: float, hc: float) -> float:
    """Ec. 6.2.3.2: As = 0.2·(f'c/fy)·bc·hc (cualquier sistema de unidades congruente)."""
    return 0.2 * fc / fy * bc * hc


def asc_min_estribo(s_m: float, fy_mpa: float, hc_m: float) -> float:
    """Ec. 6.2.3.3: Asc = 1000·s/(fy·hc), con s y hc en mm, fy en MPa y Asc en mm²; devuelve m²."""
    return 1000 * (s_m * 1000) / (fy_mpa * hc_m * 1000) * 1e-6


# --- 2.8 Propiedades de la mampostería ----------------------------------------------------
# Tabla 2.8.1.4.1 (piezas de concreto) y 2.8.1.4.2 (piezas de arcilla): f'm (MPa) a partir de
# f'p (MPa) con mortero tipo I o II; se interpola linealmente.
TABLA_FM_CONCRETO = {"fp": [6, 7.5, 10, 15, 20], "I": [2.5, 4, 5, 7.5, 10], "II": [2, 3.5, 4.5, 6, 9]}
TABLA_FM_ARCILLA = {"fp": [6, 7.5, 10, 15, 20, 30], "I": [2, 3, 4, 6, 8, 12], "II": [2, 3, 4, 6, 7, 9]}


def fm_de_tabla(fp_mpa: float, mortero: str, de_concreto: bool) -> float:
    """f'm (MPa) de las tablas 2.8.1.4.1 y 2.8.1.4.2. Fuera del intervalo se toma el extremo."""
    t = TABLA_FM_CONCRETO if de_concreto else TABLA_FM_ARCILLA
    return float(np.interp(fp_mpa, t["fp"], t[mortero]))


# Tablas 12.2.3.1.2 y 12.2.3.2.2: valores indicativos (estructuras Tipo II), MPa
FM_TIPO_II = {
    "tabique_arcilla_artesanal": 1.5, "tabique_arcilla_extruido": 2.0,
    "bloque_concreto": 1.5, "tabicon_concreto": 1.5,
}
VM_TIPO_II = 0.2


def modulo_elasticidad(fm: float, de_concreto: bool, sostenida: bool = False) -> float:
    """Ecs. 2.8.5.4: Em = 800·f'm (concreto) o 600·f'm (arcilla y otras) para cargas de corta
    duración; 350·f'm para cargas sostenidas. Mismas unidades que f'm."""
    if sostenida:
        return 350 * fm
    return (800 if de_concreto else 600) * fm


RELACION_GM = 0.2  # Gm = 0.2·Em, ec. 2.8.6.4.1
REDUCCION_G_AGRIETADO = 0.5  # 3.1.1.2.3


# --- 4.1.13 Factor de comportamiento sísmico --------------------------------------------
NIVELES_REDUCCION_Q = 6  # 4.1.13.1.1: Q − 0.5 con más de seis niveles
REDUCCION_Q = 0.5


def sistema_sismico(modalidad: str, hueca: bool, con_refuerzo_horizontal: bool) -> str:
    """Clave de `ntc_sismo.DISTORSIONES_LIMITE` (Q y γ de las tablas 4.3 de la NTC Sismo)."""
    if modalidad == "confinada":
        if hueca:
            return "mamposteria_confinada_hueca_refuerzo" if con_refuerzo_horizontal else "mamposteria_confinada_hueca"
        return "mamposteria_confinada_maciza_refuerzo" if con_refuerzo_horizontal else "mamposteria_confinada"
    if modalidad == "reforzada_interior":
        return "mamposteria_refuerzo_interior"
    return "mamposteria_no_reforzada"


# 4.1.10.1: VRi ≥ 0.8·Vui en cada entrepiso y dirección
FRACCION_CORTANTE_ENTREPISO = 0.8
# 6.3.3: muros con su eje a menos de 15° de la dirección de análisis participan totalmente
ANGULO_PARTICIPACION = 15.0

# NTC Criterios y Acciones 2023: factor de carga para combinaciones con acciones accidentales
FC_ACCIDENTAL = 1.1
