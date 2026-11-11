"""Fórmulas de referencia del reporte, con la sección de la norma de donde salen.

Cada sección del reporte muestra las fórmulas que usa con

    from .formulas import tabla_formulas
    b.append(tabla_formulas(["sa", "reduccion"]))

Para una sección nueva (diseño de concreto, mampostería, ...) basta añadir sus fórmulas a
`FORMULAS` con su referencia y pedirlas por clave. El texto es plano (sin subíndices) para
que se vea igual en PDF y Word.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bloques import Tabla


@dataclass(frozen=True)
class Formula:
    expresion: str
    significado: str
    referencia: str


NTC = "NTC Sismo 2023"

FORMULAS: dict[str, Formula] = {
    # --- espectro (3.1) ---------------------------------------------------------
    "sa": Formula(
        "Sa = a0 + (c - a0)·T/Ta, si T < Ta;   Sa = c, si Ta ≤ T < Tb;   Sa = c·p·(Tb/T)², si T ≥ Tb",
        "Espectro elástico de seudo-aceleración (fracción de g)", f"{NTC}, ec. 3.1.2a"),
    "p": Formula("p = k + (1 - k)·(Tb/T)²", "Rama descendente del espectro", f"{NTC}, ec. 3.1.2b"),
    "reduccion": Formula(
        "Sa,diseño = Sa / (Q′·R′)",
        "Espectro de diseño para Seguridad de Vida (en el modelo, «reducción» = Q′·R′)", f"{NTC}, tabla 3.1.1"),
    # --- modal (7.2) ------------------------------------------------------------
    "peso_efectivo": Formula(
        "Wei = ({φi}ᵀ[W]{J})² / ({φi}ᵀ[W]{φi});   Σ Wei ≥ 0.90 W en cada dirección",
        "Peso modal efectivo y número de modos", f"{NTC}, ec. 7.2.1"),
    "srss": Formula("S = (Σ Si²)^½", "Combinación modal SRSS (periodos que difieren 10 % o más)", f"{NTC}, ec. 7.2.2"),
    "cqc": Formula("S = (Σi Σj ρij·Si·Sj)^½", "Combinación cuadrática completa (CQC)", f"{NTC}, ec. 7.2.3"),
    "rho": Formula(
        "ρij = 8ζ²(1 + r)·r^1.5 / [(1 - r²)² + 4ζ²·r·(1 + r)²],   r = ωi/ωj",
        "Coeficiente de correlación modal, ζ = 0.05", f"{NTC}, ec. 7.2.4"),
    # --- cortante mínimo (7.5) -------------------------------------------------
    "cortante_minimo": Formula(
        "Vo ≥ amin·Wo;   si no, fuerzas de diseño × amin·Wo/Vo (los desplazamientos no se escalan)",
        "Cortante basal mínimo del análisis modal espectral", f"{NTC}, 7.5"),
    "amin": Formula(
        "amin = 0.04/R′ si Ts < 0.5 s;   0.06/R′ si Ts ≥ 1.0 s;   lineal entre ambos",
        "Ts: periodo dominante más largo del terreno", f"{NTC}, 7.5"),
    # --- torsión (2.3) ---------------------------------------------------------
    "excentricidad_diseno": Formula(
        "M = F·(1.5es + ea)  o  F·(es - ea), el más desfavorable;  en análisis dinámico es con factor 1",
        "Momento torsionante de diseño", f"{NTC}, ecs. 2.3.1a y 2.3.1b"),
    "ea": Formula(
        "eai = [0.05 + 0.05·(i - 1)/(n - 1)]·bi",
        "Excentricidad accidental del entrepiso i; bi perpendicular al sismo, n pisos", f"{NTC}, ec. 2.3.2"),
    "momento_torsion": Formula(
        "Mai = Vi·eai;   M0i = ±[Mai - Ma(i+1)]",
        "Momento aplicado en el nivel i (cargas en el plano de cada piso)", f"{NTC}, ec. 2.3.3"),
    # --- componentes ortogonales (2.5) ------------------------------------------
    "ortogonal": Formula(
        "E = 1.0·Ex + 0.3·Ey   o   E = 0.3·Ex + 1.0·Ey, con los signos más desfavorables",
        "Efectos bidireccionales", f"{NTC}, 2.5"),
    # --- distorsiones (1.7) -----------------------------------------------------
    "distorsion": Formula("γ = (δi - δi-1)/hi", "Distorsión de entrepiso, la mayor de los elementos verticales", f"{NTC}, 1.7"),
    "seguridad_vida": Formula(
        "γ·Q·R′ ≤ γSV", "Seguridad de Vida: γ con el espectro de diseño reducido", f"{NTC}, 1.7 y tablas 4.3"),
    "ocupacion_inmediata": Formula(
        "γ ≤ γOI", "Ocupación Inmediata (Grupo A): γ con el espectro elástico (Q = 1)", f"{NTC}, 1.7 y tablas 4.3"),
    "limitacion_dano": Formula(
        "γ ≤ 0.002  (0.004 con elementos no estructurales separados o deformables)",
        "Limitación de Daño No Estructural (Grupo B): γ con el espectro elástico × Ks", f"{NTC}, 1.7"),
    "ks": Formula(
        "Ks = 1/6 (zona A);   1/[6 - 4(Ts - 0.5)] (zona B);   1/4 (zona C)",
        "Paso de la intensidad base de diseño a la frecuente", f"{NTC}, ec. 3.1.1"),
}


def tabla_formulas(claves: list[str], titulo: str = "Fórmulas de referencia") -> Tabla:
    filas = [[FORMULAS[k].expresion, FORMULAS[k].significado, FORMULAS[k].referencia] for k in claves]
    return Tabla(["Expresión", "Significado", "Referencia"], filas, titulo=titulo,
                 anchos=[0.46, 0.34, 0.20], texto={0, 1, 2})
