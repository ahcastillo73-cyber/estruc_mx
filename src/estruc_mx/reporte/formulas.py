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
NTCM = "NTC Mampostería 2023"

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
    # --- mampostería: propiedades (2.8) --------------------------------------
    "mam_em": Formula(
        "Em = 600·f'm (arcilla y otras) u 800·f'm (concreto), cargas de corta duración;  350·f'm, sostenidas",
        "Módulo de elasticidad de la mampostería", f"{NTCM}, ecs. 2.8.5.4"),
    "mam_gm": Formula(
        "Gm = 0.2·Em;  agrietado 0.5·Gm",
        "Módulo de cortante (en el plano de los muros); agrietamiento en los niveles inferiores",
        f"{NTCM}, ec. 2.8.6.4.1 y 3.1.1.2"),
    # --- carga vertical (3.1.2.3, 6.4.1, 7.3.1) ----------------------------------
    "mam_pr": Formula(
        "PR = FR·FE·(f'm·AT + ΣAs·fy),  FR = 0.6;  en muros con refuerzo interior PR ≤ 1.25·FR·FE·f'm·AT",
        "Carga vertical resistente; AT = t·L con L entre ejes de castillos", f"{NTCM}, ecs. 6.4.1.1 y 7.3.1.1"),
    "mam_fe": Formula(
        "FE = 0.7 (muros interiores) o 0.6 (extremos), si H/t ≤ 20, e ≤ t/6 y apoyo lateral arriba y abajo",
        "Factor de reducción por excentricidad y esbeltez, valores aproximados", f"{NTCM}, 3.1.2.3.1 a"),
    "mam_fe_ec": Formula(
        "FE = (1 - 2e′/t)·[1 - (kH/(30t))²],  e′ = ec + t/24,  ec = t/2 - b/3",
        "FE general; k = 1 en muros extremos, 0.8 entre losas continuas, 2 sin apoyo arriba",
        f"{NTCM}, ecs. 3.1.2.3.1 y 3.1.2.2.2"),
    # --- cortante (6.5, 7.4) -------------------------------------------------------
    "mam_vr": Formula("VR = VmR + VsR,  FR = 0.7", "Resistencia a cargas laterales", f"{NTCM}, ec. 6.5.1.1 y 4.1.6.4"),
    "mam_vmr": Formula(
        "VmR = FR·(0.5·v'm·AT + 0.3·P)·f ≤ 1.5·FR·v'm·AT·f",
        "Cortante de la mampostería; P en compresión sin factor de carga, la menor con sismo; con tensión VmR = 0",
        f"{NTCM}, ec. 6.5.2.1 y 6.5.2.3"),
    "mam_f": Formula(
        "f = 1.5 si H/L ≤ 0.2;  f = 1.0 si H/L ≥ 1.0;  lineal entre ambos", "Factor por relación de aspecto",
        f"{NTCM}, ec. 6.5.2.4"),
    "mam_vsr": Formula(
        "VsR = FR·η·(ph·fyh)e·AT,  ph = Ash/(sh·t),  (ph·fyh)e = ph·fyh ≤ 0.1·f'm·fan",
        "Cortante del refuerzo horizontal", f"{NTCM}, ecs. 6.5.3.4.1.a a c"),
    "mam_eta": Formula(
        "η = VmR/(FR·(ph·fyh)e·AT)·(k0·k1 - 1) + ηs (compresión);  η = k1·ηs (tensión)",
        "Eficiencia del refuerzo horizontal", f"{NTCM}, ecs. 6.5.3.4.1.d y h"),
    "mam_k0k1": Formula(
        "k0 = 1.3 si H/L ≤ 1.0, 1.0 si H/L ≥ 1.5;  k1 = 1 - α·(ph·fyh)e, α = 0.45/MPa;  "
        "ηs = 0.55 si f'm ≤ 6 MPa, 0.75 si f'm ≥ 9 MPa",
        "Factores de la eficiencia (interpolados)", f"{NTCM}, ecs. 6.5.3.4.1.e a g"),
    # --- flexocompresión (6.4.2.2, 7.3.2.2) ----------------------------------------
    "mam_mr": Formula(
        "MR = FR·Mo + 0.3·Pu·d, si 0 ≤ Pu ≤ PR/3 (FR = 0.8);  MR = (1.5·FR·Mo + 0.15·PR·d)·(1 - Pu/PR), "
        "si Pu > PR/3 (FR = 0.6)",
        "Momento resistente en el plano, método optativo; Mo = As·fy·d′", f"{NTCM}, ecs. 6.4.2.2.1.a y b"),
    "mam_mr_tension": Formula(
        "MR = 0.8·Mo·(1 - Pu/(ΣAs·fy)) con Pu de tensión",
        "Interpolación entre tensión pura y flexión pura", f"{NTCM}, 6.4.2.2.2"),
    # --- requisitos de castillos (6.2) ----------------------------------------------
    "mam_as": Formula("As ≥ 0.2·(f'c/fy)·bc·hc, con cuatro barras o más", "Refuerzo longitudinal mínimo de castillos y dalas",
                      f"{NTCM}, ec. 6.2.3.2"),
    "mam_asc": Formula(
        "Asc ≥ 1000·s/(fy·hc) (mm, MPa);  s ≤ 1.5t y ≤ 200 mm;  s ≤ hc/2 en Ho = max(H/6, 400 mm)",
        "Estribos de castillos y dalas", f"{NTCM}, ec. 6.2.3.3 y 6.2.3.2"),
    "mam_sep": Formula(
        "Castillos en extremos e intersecciones a ≤ 1.5H y ≤ 4 m;  dalas a ≤ 3 m;  t ≥ 120 mm;  H/t ≤ 25",
        "Requisitos de mampostería confinada", f"{NTCM}, 6.1.3, 6.2.1.1 y 6.2.1.2"),
    # --- entrepiso (4.1.10 a 4.1.12) ---------------------------------------------------
    "mam_entrepiso": Formula(
        "VRi = FR·(0.5·v'm + 0.3·σi + η·(ph·fyh)e)·ΣAT ≥ 0.8·Vui,  σi ≤ 3.33·v'm",
        "Cortante resistente de entrepiso; σi = peso sobre el entrepiso / área de todos sus muros",
        f"{NTCM}, ecs. 4.1.10.1 y 4.1.12.1"),
    "mam_fc": Formula(
        "Vu = 1.1·Vsismo;  Pu = 1.1·(Pg ± Psismo) o 0.9·Pg - 1.1·Psismo",
        "Factores de carga con acciones accidentales y efecto favorable",
        "NTC Criterios y Acciones 2023, 3.4.1 b y c"),
}


def tabla_formulas(claves: list[str], titulo: str = "Fórmulas de referencia") -> Tabla:
    filas = [[FORMULAS[k].expresion, FORMULAS[k].significado, FORMULAS[k].referencia] for k in claves]
    return Tabla(["Expresión", "Significado", "Referencia"], filas, titulo=titulo,
                 anchos=[0.46, 0.34, 0.20], texto={0, 1, 2})
