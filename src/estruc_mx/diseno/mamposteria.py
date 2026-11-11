"""Revisión de muros de mampostería según la NTC Mampostería 2023 (CDMX).

Para cada muro de un material de tipo «mamposteria» se revisa, con sus castillos (ver
analisis/pilas.py):

1. Requisitos de geometría y refuerzo: espesor y esbeltez (6.1.3, 7.1.2), castillos y dalas
   (6.2.1 a 6.2.3), refuerzo horizontal (6.5.2.2, 6.5.3) y cuantías de muros reforzados
   interiormente (7.1.5).
2. Carga vertical: Pu ≤ PR = FR·FE·(f'm·AT + ΣAs·fy) (6.4.1, 7.3.1), con FE de 3.1.2.3.
3. Cortante en el plano: Vu ≤ VR = VmR + VsR (6.5, 7.4), con P sin factor de carga y la menor
   compresión con sismo (6.5.2.3).
4. Flexocompresión en el plano por el método optativo (6.4.2.2, 7.3.2.2).
5. Cortante resistente de cada entrepiso: VRi ≥ 0.8·Vui (4.1.10 a 4.1.12).

Fuerzas de diseño:
- Gravedad: las combinaciones del modelo que no tienen sismo ni viento, ya factorizadas.
- Sismo: las fuerzas sísmicas de diseño de la revisión sísmica (escaladas por cortante mínimo,
  con torsión accidental y 100/30) por el factor de carga accidental 1.1, más la gravedad de la
  combinación que acompaña al sismo (carga muerta más viva instantánea). Por defecto se toma la
  fuente de masa del modelo, que es esa combinación.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..analisis.areas import BaseMuro, bases_muros
from ..analisis.pilas import CastilloMuro, castillos_muros, todas_fuerzas_pilas
from ..modelo import (
    Combinacion,
    Edificio,
    PropiedadesMamposteria,
    RefuerzoMuroMamposteria,
)
from ..modelo.malla import Malla, discretizar
from ..motores import Resultados
from ..motores.comun import combinaciones_efectivas
from ..normas import ntc_mamposteria as N
from ..normas.ntc_sismo import DISTORSIONES_LIMITE

NOMBRE_COMBO_SISMO = "Gravedad con sismo (CM + CVa)"
MPA = 1000.0  # kPa


@dataclass
class CriteriosMamposteria:
    # Combinación de servicio (sin factorizar) que acompaña al sismo; None = fuente de masa
    combinacion_sismo: str | None = None
    # Combinaciones factorizadas de gravedad; None = las del modelo sin patrones de sismo ni viento
    combinaciones_gravedad: list[str] | None = None
    fc_accidental: float = N.FC_ACCIDENTAL
    fc_favorable: float = 0.9  # NTC Criterios y Acciones 3.4.1 c), carga vertical que ayuda


@dataclass
class Comprobacion:
    """Una revisión. En las de resistencia `demanda` y `capacidad` son la acción de diseño y la
    resistencia; en los requisitos, el valor del muro y el límite de la norma."""

    concepto: str
    articulo: str
    cumple: bool
    demanda: float | None = None
    capacidad: float | None = None
    unidad: str = ""
    detalle: str = ""
    resistencia: bool = False

    @property
    def relacion(self) -> float | None:
        """Demanda / resistencia (> 1 no cumple); None en los requisitos."""
        if not self.resistencia or self.demanda is None or self.capacidad is None:
            return None
        if self.capacidad <= 0:
            return math.inf if self.demanda > 0 else 0.0
        return self.demanda / self.capacidad


@dataclass
class RevisionMuro:
    muro: str
    seccion: str
    material: str
    modalidad: str
    z: float  # elevación de la base, m
    direccion: str  # "X", "Y" o el ángulo del muro respecto a X
    angulo: float  # grados, 0 a 180
    L: float  # longitud (entre ejes de castillos extremos), m
    H: float  # altura libre, m
    t: float  # espesor, m
    extremo: bool
    AT: float = 0.0
    n_castillos: float = 0.0  # castillos de la pila (los compartidos cuentan su fracción)
    # Carga vertical
    FE: float = 0.0
    origen_FE: str = ""
    PR: float = 0.0
    Pu: float = 0.0
    combinacion_Pu: str = ""
    # Cortante
    P_cortante: float | None = None  # compresión (+) mínima sin factorizar con sismo, kN
    f: float = 1.0
    ph_fyh: float = 0.0  # kPa
    ph_fyh_e: float = 0.0
    eta: float = 0.0
    VmR: float = 0.0
    VsR: float = 0.0
    Vu: float | None = None
    # Flexocompresión
    Mo: float = 0.0
    d: float = 0.0
    Mu: float | None = None
    Pu_flexion: float | None = None
    MR: float | None = None
    origen_flexion: str = ""
    comprobaciones: list[Comprobacion] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def VR(self) -> float:
        return self.VmR + self.VsR

    @property
    def cumple(self) -> bool:
        return all(c.cumple for c in self.comprobaciones)

    @property
    def relacion(self) -> float:
        """La mayor relación demanda/capacidad de las resistencias revisadas."""
        r = [c.relacion for c in self.comprobaciones if c.relacion is not None]
        return max(r) if r else 0.0

    def comprobacion(self, concepto: str) -> Comprobacion | None:
        return next((c for c in self.comprobaciones if c.concepto == concepto), None)


@dataclass
class CortanteEntrepiso:
    direccion: str
    z_base: float
    z_tope: float
    muros: list[str]
    AT: float  # suma de áreas de los muros en la dirección, m²
    sigma: float  # esfuerzo normal promedio, kPa (ya limitado a 3.33·v'm)
    VR: float  # kN
    Vu: float  # kN, cortante sísmico de diseño del entrepiso (con FC)

    @property
    def cumple(self) -> bool:
        return self.VR >= N.FRACCION_CORTANTE_ENTREPISO * self.Vu

    @property
    def relacion(self) -> float:
        return N.FRACCION_CORTANTE_ENTREPISO * self.Vu / self.VR if self.VR > 0 else math.inf


@dataclass
class RevisionMamposteria:
    criterios: CriteriosMamposteria
    muros: list[RevisionMuro] = field(default_factory=list)
    entrepisos: list[CortanteEntrepiso] = field(default_factory=list)
    combinaciones_gravedad: list[str] = field(default_factory=list)
    combinacion_sismo: str = ""
    factores_sismo: dict[str, float] = field(default_factory=dict)
    con_sismo: bool = False
    sistema: str = ""  # clave de DISTORSIONES_LIMITE
    Q: float = 0.0
    niveles: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def cumple(self) -> bool:
        return all(m.cumple for m in self.muros) and all(e.cumple for e in self.entrepisos)

    def muro(self, area: str) -> RevisionMuro | None:
        return next((m for m in self.muros if m.muro == area), None)


# --- utilidades ------------------------------------------------------------------------
def muros_de_mamposteria(modelo: Edificio) -> list[str]:
    out = []
    for a in modelo.areas:
        if a.tipo != "muro":
            continue
        s = modelo.seccion_area(a.seccion)
        if modelo.material(s.material).tipo == "mamposteria":
            out.append(a.id)
    return out


def propiedades(modelo: Edificio, material: str) -> tuple[PropiedadesMamposteria, bool]:
    """Propiedades de diseño del material; si no tiene, los valores indicativos de la NTC para
    estructuras Tipo II (tablas 12.2.3.1.2 y 12.2.3.2.2). El bool dice si se supusieron."""
    m = modelo.material(material)
    if m.mamposteria is not None:
        return m.mamposteria, False
    return PropiedadesMamposteria(
        pieza="tabique_arcilla_artesanal", fm=N.FM_TIPO_II["tabique_arcilla_artesanal"] * MPA, vm=N.VM_TIPO_II * MPA,
    ), True


def _direccion(e1: np.ndarray) -> tuple[str, float]:
    ang = math.degrees(math.atan2(e1[1], e1[0])) % 180.0
    if min(ang, 180 - ang) < N.ANGULO_PARTICIPACION:
        return "X", ang
    if abs(ang - 90) < N.ANGULO_PARTICIPACION:
        return "Y", ang
    return f"{ang:.0f}°", ang


def _extremos_auto(modelo: Edificio, bases: dict[str, BaseMuro], ids: list[str]) -> dict[str, bool]:
    """Muro extremo: su eje está sobre el contorno (rectángulo envolvente) de los muros del nivel."""
    out = {}
    por_nivel: dict[float, list[str]] = {}
    for a in ids:
        por_nivel.setdefault(round(bases[a].elevacion, 3), []).append(a)
    for lista in por_nivel.values():
        pts = np.array([p for a in lista for p in modelo.esquinas(modelo.area(a))[:, :2]])
        xmin, ymin = pts.min(axis=0)
        xmax, ymax = pts.max(axis=0)
        for a in lista:
            c = bases[a].centro
            tol = 0.05 + modelo.seccion_area(modelo.area(a).seccion).espesor
            out[a] = bool(min(abs(c[0] - xmin), abs(c[0] - xmax), abs(c[1] - ymin), abs(c[1] - ymax)) <= tol)
    return out


def _combinaciones_gravedad(modelo: Edificio, crit: CriteriosMamposteria) -> list[str]:
    if crit.combinaciones_gravedad is not None:
        return list(crit.combinaciones_gravedad)
    laterales = {p.nombre for p in modelo.patrones if p.tipo in ("sismo", "viento")}
    return [c.nombre for c in combinaciones_efectivas(modelo) if not (set(c.factores) & laterales)]


def _fuerzas_estaticas(modelo: Edificio, malla: Malla, res: Resultados, combos: list[str], bases, cast):
    out = {}
    for c in combos:
        if c in res.desplazamientos:
            out[c] = todas_fuerzas_pilas(modelo, malla, res.fuerzas_elementos.get(c, {}), res.desplazamientos[c], c,
                                         bases=bases, castillos=cast)
    return out


def _gravedad_sismo(modelo: Edificio, malla, estatico: Resultados | None, crit: CriteriosMamposteria, motor, bases, cast,
                    avisos: list[str]):
    """(nombre, factores, fuerzas por muro) de la gravedad de servicio que acompaña al sismo."""
    combos = {c.nombre: c for c in combinaciones_efectivas(modelo)}
    if crit.combinacion_sismo is not None:
        if crit.combinacion_sismo not in combos:
            raise ValueError(f"combinación '{crit.combinacion_sismo}' no existe")
        fac = combos[crit.combinacion_sismo].factores
        nombre = crit.combinacion_sismo
    else:
        fac = dict(modelo.fuente_masa)
        if modelo.peso_propio_en_masa:
            # El peso propio entra en la masa aunque ningún patrón lo lleve
            for p in modelo.patrones:
                if p.peso_propio and p.nombre not in fac:
                    fac[p.nombre] = 0.0
        if not fac:
            fac = {p.nombre: 1.0 for p in modelo.patrones if p.tipo == "muerta"}
        nombre = NOMBRE_COMBO_SISMO
        for c in combos.values():
            if c.factores == fac:
                nombre = c.nombre
                break
    if estatico is not None and nombre in estatico.desplazamientos:
        return nombre, fac, _fuerzas_estaticas(modelo, malla, estatico, [nombre], bases, cast)[nombre]
    if motor is None:
        avisos.append(f"No hay resultados de «{nombre}» (gravedad que acompaña al sismo): no se revisó el cortante.")
        return nombre, fac, None
    m = modelo.model_copy(deep=True)
    m.combinaciones = [Combinacion(nombre=nombre, factores=fac)]
    res = motor.analizar(m)
    return nombre, fac, _fuerzas_estaticas(m, malla, res, [nombre], bases, cast)[nombre]


# --- resistencias ------------------------------------------------------------------------
def factor_FE(t: float, H: float, extremo: bool) -> tuple[float, str]:
    """FE de 3.1.2.3.1. Con H/t ≤ 20 los valores simplificados de a); si no, el menor con la
    ec. 3.1.2.3.1, e′ = ec + t/24 (ec = t/2 − b/3 con b = t en muros extremos), k = 1 en extremos
    y 0.8 en interiores."""
    simple = N.FE_EXTREMO if extremo else N.FE_INTERIOR
    tipo = "extremo" if extremo else "interior"
    if H / t <= N.ESBELTEZ_FE_SIMPLIFICADO:
        return simple, f"muro {tipo}, H/t = {H / t:.1f} ≤ 20: FE = {simple:g} (3.1.2.3.1 a)"
    ec = N.excentricidad_extremo(t, t) if extremo else 0.0
    k = N.K_ALTURA_EXTREMO if extremo else N.K_ALTURA_INTERIOR
    fe = N.fe_ecuacion(ec + t / 24, t, k, H)
    return min(simple, fe), (f"muro {tipo}, H/t = {H / t:.1f} > 20: ec. 3.1.2.3.1 con e′ = {ec + t / 24:.4f} m, "
                             f"k = {k:g}: FE = {fe:.3f}")


def momento_resistente(Pu: float, PR: float, Mo: float, d: float, As_fy_total: float) -> tuple[float, str]:
    """MR por el método optativo (ecs. 6.4.2.2.1 a y b, 7.3.2.2.1); con tensión se interpola
    entre ΣAs·fy y Mo con FR = 0.8 (6.4.2.2.2). Pu > 0 compresión."""
    if Pu < 0:
        if As_fy_total <= 0:
            return 0.0, "tensión sin acero"
        return max(0.0, N.FR_FLEXION_BAJA_CARGA * Mo * (1 - (-Pu) / As_fy_total)), "tensión, 6.4.2.2.2"
    if Pu <= PR / 3:
        return N.FR_FLEXION_BAJA_CARGA * Mo + 0.3 * Pu * d, "ec. 6.4.2.2.1.a, FR = 0.8"
    return max(0.0, (1.5 * N.FR_FLEXION_ALTA_CARGA * Mo + 0.15 * PR * d) * (1 - Pu / PR)), "ec. 6.4.2.2.1.b, FR = 0.6"


def cortante_resistente(rm: RevisionMuro, prop: PropiedadesMamposteria, ref: RefuerzoMuroMamposteria) -> None:
    """VmR (6.5.2, 7.4.2) y VsR (6.5.3.4, 7.4.3.5) en `rm`, con rm.P_cortante ya calculado."""
    FR = N.FR_CORTANTE
    vm, AT = prop.vm, rm.AT
    rm.f = N.factor_f(rm.H / rm.L)
    P = rm.P_cortante or 0.0
    if P >= 0:
        rm.VmR = min(FR * (0.5 * vm * AT + 0.3 * P) * rm.f, N.LIMITE_VMR * FR * vm * AT * rm.f)
    else:
        rm.VmR = 0.0  # 6.5.2.3: con tensión no se cuenta la mampostería
    if rm.modalidad == "no_reforzada":
        rm.VsR = 0.0
        return
    rm.ph_fyh = ref.ph_fyh(rm.t)
    fan = prop.fan if rm.modalidad == "confinada" else ref.fnm
    rm.ph_fyh_e = min(rm.ph_fyh, N.PH_FYH_EFECTIVO * prop.fm * fan)
    if rm.ph_fyh_e <= 0:
        rm.VsR, rm.eta = 0.0, 0.0
        return
    k1 = 1 - N.ALFA * rm.ph_fyh_e / MPA
    es = N.eta_s(prop.fm / MPA)
    if P >= 0:
        rm.eta = rm.VmR / (FR * rm.ph_fyh_e * AT) * (N.k0(rm.H / rm.L) * k1 - 1) + es
    else:
        rm.eta = k1 * es
    rm.eta = max(rm.eta, 0.0)
    rm.VsR = FR * rm.eta * rm.ph_fyh_e * AT


# --- requisitos ---------------------------------------------------------------------------
def _requisitos(rm: RevisionMuro, prop: PropiedadesMamposteria, ref: RefuerzoMuroMamposteria,
                castillos: list[CastilloMuro], hay_losa_10: bool, modelados: bool) -> list[Comprobacion]:
    t, H, L = rm.t, rm.H, rm.L
    c: list[Comprobacion] = []
    art_t = "6.1.3" if rm.modalidad == "confinada" else "7.1.2"
    c.append(Comprobacion("Espesor mínimo", art_t, t >= N.ESPESOR_MIN - 1e-9, t * 100, N.ESPESOR_MIN * 100, "cm",
                          "t ≥ 120 mm (estructuras Tipo I)"))
    c.append(Comprobacion("Esbeltez H/t", art_t, H / t <= N.ESBELTEZ_MAX + 1e-9, H / t, N.ESBELTEZ_MAX, "",
                          "H/t ≤ 25"))
    if rm.modalidad == "confinada":
        bmin = max(N.CASTILLO_B_MIN, t)
        c.append(Comprobacion("Castillo: bc", "6.2.1.1 b", ref.castillo_b >= bmin - 1e-9, ref.castillo_b * 100, bmin * 100,
                              "cm", "bc ≥ 120 mm y ≥ t (castillos externos)"))
        c.append(Comprobacion("Castillo: hc", "6.2.1.1 b", ref.castillo_h >= N.CASTILLO_H_MIN - 1e-9, ref.castillo_h * 100,
                              N.CASTILLO_H_MIN * 100, "cm", "hc ≥ 150 mm"))
        smax = min(N.SEP_CASTILLOS_ALTURA * H, N.SEP_CASTILLOS_MAX)
        if modelados:
            pos = sorted(x.posicion for x in castillos)
            extremos = len(pos) >= 2 and pos[0] <= -L / 2 + 0.05 and pos[-1] >= L / 2 - 0.05
            puntos = [-L / 2, *pos, L / 2]
            hueco = max(b - a for a, b in zip(puntos, puntos[1:]))
            c.append(Comprobacion("Castillos en los extremos", "6.2.1.1 a", extremos, detalle=(
                "castillos modelados en ambos extremos" if extremos else "falta un castillo en un extremo del muro")))
            c.append(Comprobacion("Separación de castillos", "6.2.1.1 a", hueco <= smax + 1e-6, hueco, smax, "m",
                                  "≤ 1.5H y ≤ 4 m"))
        else:
            n = max(0, math.ceil(L / smax - 1e-9) - 1)
            c.append(Comprobacion("Separación de castillos", "6.2.1.1 a", True, L / (n + 1), smax, "m",
                                  f"castillos no modelados: se suponen en los extremos y {n} intermedios"))
        c.append(Comprobacion("Castillo: número de barras", "6.2.2.2", ref.castillo_barras >= N.BARRAS_CASTILLO_MIN,
                              detalle=f"{ref.castillo_barras} barras (mínimo 4)"))
        As_min = N.as_min_castillo(ref.castillo_fc, ref.castillo_fy, ref.castillo_b, ref.castillo_h)
        c.append(Comprobacion("Castillo: As mínimo", "ec. 6.2.3.2", ref.castillo_As >= As_min * (1 - 1e-9),
                              ref.castillo_As * 1e4, As_min * 1e4, "cm²", "As ≥ 0.2·(f'c/fy)·bc·hc"))
        Asc_min = N.asc_min_estribo(ref.estribo_s, ref.estribo_fy / MPA, ref.castillo_h)
        c.append(Comprobacion("Castillo: estribos Asc", "ec. 6.2.3.3", ref.estribo_Asc >= Asc_min * (1 - 1e-9),
                              ref.estribo_Asc * 1e4, Asc_min * 1e4, "cm²", "Asc ≥ 1000·s/(fy·hc), s y hc en mm, fy en MPa"))
        s_max = min(1.5 * t, N.ESTRIBO_S_MAX)
        c.append(Comprobacion("Castillo: separación de estribos", "6.2.2.3", ref.estribo_s <= s_max + 1e-9,
                              ref.estribo_s * 100, s_max * 100, "cm", "s ≤ 1.5t y ≤ 200 mm"))
        Ho = max(H / 6, N.HO_MIN)
        c.append(Comprobacion("Castillo: estribos en los extremos", "6.2.3.2",
                              ref.estribo_s_extremo <= ref.castillo_h / 2 + 1e-9, ref.estribo_s_extremo * 100,
                              ref.castillo_h / 2 * 100, "cm", f"s ≤ hc/2 en Ho = {Ho:.2f} m de cada extremo"))
        c.append(Comprobacion("Concreto de castillos y dalas", "6.2.1.3.1", ref.castillo_fc >= N.FC_CASTILLOS_MIN * MPA - 1e-6,
                              ref.castillo_fc / MPA, N.FC_CASTILLOS_MIN, "MPa", "f'c ≥ 20 MPa"))
        dala_ok = ref.dala_b >= max(N.DALA_B_MIN, t) - 1e-9 and (
            ref.dala_h >= N.DALA_H_MIN - 1e-9 or (hay_losa_10 and ref.dala_h >= 0.10 - 1e-9))
        c.append(Comprobacion("Dala: dimensiones", "6.2.1.2 b", dala_ok, detalle=(
            f"{ref.dala_b * 100:.0f} × {ref.dala_h * 100:.0f} cm; mínimo 12 cm (y t) × 15 cm, o el peralte de una "
            "losa de 10 cm o más")))
        c.append(Comprobacion("Separación de dalas", "6.2.1.2 a", H <= N.SEP_DALAS_MAX + 1e-6, H, N.SEP_DALAS_MAX, "m",
                              "dalas en los extremos horizontales del muro y a no más de 3 m"))
    if rm.modalidad != "no_reforzada":
        if prop.vm >= N.VM_REFUERZO_HORIZONTAL * MPA - 1e-6:
            c.append(Comprobacion("Refuerzo horizontal obligatorio", "6.5.2.2", rm.ph_fyh > 0,
                                  detalle="v'm ≥ 1 MPa: el muro debe llevar refuerzo horizontal"))
        if rm.ph_fyh > 0 or rm.modalidad == "reforzada_interior":
            fan = prop.fan if rm.modalidad == "confinada" else ref.fnm
            phmax = max(N.PH_FYH_MIN, N.PH_FYH_MAX * prop.fm / MPA * fan)
            art = "6.5.3.3" if rm.modalidad == "confinada" else "7.4.3.4"
            c.append(Comprobacion("ph·fyh mínimo", art, rm.ph_fyh >= N.PH_FYH_MIN * MPA - 1e-6, rm.ph_fyh / MPA,
                                  N.PH_FYH_MIN, "MPa", "ph·fyh ≥ 0.3 MPa"))
            c.append(Comprobacion("ph·fyh máximo", art, rm.ph_fyh <= phmax * MPA + 1e-6, rm.ph_fyh / MPA, phmax, "MPa",
                                  "ph·fyh ≤ 0.15·f'm·fan, no menor que 0.3 MPa"))
            if rm.ph_fyh > 0:
                c.append(Comprobacion("Separación del refuerzo horizontal", "6.5.3.2", ref.sh <= N.SH_MAX + 1e-9,
                                      ref.sh * 100, N.SH_MAX * 100, "cm", "sh ≤ 450 mm y seis hiladas"))
                c.append(Comprobacion("fyh máximo", "6.5.3.1.3", ref.fyh <= N.FYH_MAX * MPA + 1e-6, ref.fyh / MPA,
                                      N.FYH_MAX, "MPa"))
                c.append(Comprobacion("Ash en la junta", "6.5.3.3.2", ref.Ash <= N.ASH_JUNTA * ref.junta * t + 1e-12,
                                      ref.Ash * 1e4, N.ASH_JUNTA * ref.junta * t * 1e4, "cm²", "Ash ≤ 0.05·hj·t"))
        if rm.modalidad == "reforzada_interior":
            suma = (rm.ph_fyh + ref.pv_fyv) / MPA
            c.append(Comprobacion("Cuantías ph·fyh + pv·fyv", "ec. 7.1.5.1.a",
                                  suma >= N.PHFYH_PVFYV_MIN - 1e-9 and ref.pv_fyv >= N.PH_FYH_MIN * MPA - 1e-6,
                                  suma, N.PHFYH_PVFYV_MIN, "MPa", "≥ 0.84 MPa y cada una ≥ 0.3 MPa"))
    return c


# --- revisión ------------------------------------------------------------------------------
def revisar_mamposteria(modelo: Edificio, estatico: Resultados | None, revision=None, respuestas=None, motor=None,
                        criterios: CriteriosMamposteria | None = None) -> RevisionMamposteria:
    """`revision` es la RevisionSismica (fuerzas de diseño de los muros); `respuestas`, las
    espectrales en X y Y (cortantes de entrepiso); `motor` resuelve la gravedad que acompaña al
    sismo si `estatico` no la tiene."""
    crit = criterios or CriteriosMamposteria()
    out = RevisionMamposteria(criterios=crit)
    ids = muros_de_mamposteria(modelo)
    if not ids:
        out.avisos.append("El modelo no tiene muros de mampostería (material de tipo «mamposteria»).")
        return out
    malla = discretizar(modelo)
    bases = bases_muros(modelo, malla)
    cast = castillos_muros(modelo, malla, bases)
    modelados = any(cast[a] for a in ids)
    hay_losa_10 = any(s.tipo == "losa" and s.espesor >= 0.10 - 1e-9 for s in modelo.secciones_area)
    extremos = _extremos_auto(modelo, bases, ids)

    # --- fuerzas -----------------------------------------------------------------------
    out.combinaciones_gravedad = _combinaciones_gravedad(modelo, crit)
    grav = _fuerzas_estaticas(modelo, malla, estatico, out.combinaciones_gravedad, bases, cast) if estatico else {}
    if not grav:
        out.avisos.append("Sin análisis estático de gravedad: no se revisó la carga vertical.")
    sismo = None
    if revision is not None:
        sismo = revision.fuerzas_pilas or revision.fuerzas_muros
        if modelados and not revision.fuerzas_pilas:
            out.avisos.append("La revisión sísmica no trae fuerzas con castillos; se usaron las de los muros solos.")
    g_sis = None
    if sismo:
        out.combinacion_sismo, out.factores_sismo, g_sis = _gravedad_sismo(modelo, malla, estatico, crit, motor, bases, cast,
                                                                           out.avisos)
        out.con_sismo = g_sis is not None
    else:
        out.avisos.append("Sin revisión sísmica (espectro y análisis modal): no se revisaron cortante ni flexocompresión "
                          "por sismo.")
    FC = crit.fc_accidental

    con_refuerzo = False
    for a in ids:
        area = modelo.area(a)
        s = modelo.seccion_area(area.seccion)
        prop, supuesta = propiedades(modelo, s.material)
        ref = s.mamposteria or RefuerzoMuroMamposteria()
        b = bases[a]
        zs = [modelo.nodo(n).z for n in area.nodos]
        H = max(zs) - min(zs)
        direccion, ang = _direccion(b.ejes[0])
        ext = area.extremo if area.extremo is not None else extremos[a]
        rm = RevisionMuro(muro=a, seccion=s.nombre, material=s.material, modalidad=ref.modalidad, z=b.elevacion,
                          direccion=direccion, angulo=ang, L=b.longitud, H=H, t=s.espesor, extremo=ext)
        if supuesta:
            rm.avisos.append(f"El material «{s.material}» no tiene propiedades de mampostería: se usaron f'm = "
                             f"{prop.fm / MPA:g} MPa y v'm = {prop.vm / MPA:g} MPa (tablas 12.2.3, Tipo II).")
        if s.mamposteria is None:
            rm.avisos.append(f"La sección «{s.nombre}» no tiene refuerzo definido: se supuso mampostería confinada con "
                             "castillos de 15 × 15 cm, 4 #3, sin refuerzo horizontal.")
        rm.AT = rm.t * rm.L
        cs = cast.get(a, [])
        if rm.modalidad == "confinada":
            rm.n_castillos = sum(c.fraccion for c in cs) if modelados else 1.0 + max(
                0, math.ceil(rm.L / min(N.SEP_CASTILLOS_ALTURA * H, N.SEP_CASTILLOS_MAX) - 1e-9) - 1)
            As_total = rm.n_castillos * ref.castillo_As
        elif rm.modalidad == "reforzada_interior":
            rm.n_castillos = 2.0
            As_total = 2 * ref.castillo_As
        else:
            As_total = 0.0
        rm.ph_fyh = ref.ph_fyh(rm.t) if rm.modalidad != "no_reforzada" else 0.0
        con_refuerzo |= rm.ph_fyh > 0

        # --- carga vertical (6.4.1, 7.3.1) ---------------------------------------------
        rm.FE, rm.origen_FE = factor_FE(rm.t, H, ext)
        FR = N.FR_COMPRESION
        rm.PR = FR * rm.FE * (prop.fm * rm.AT + As_total * ref.castillo_fy)
        if rm.modalidad == "reforzada_interior":
            rm.PR = min(rm.PR, 1.25 * FR * rm.FE * prop.fm * rm.AT)
        if grav:
            rm.combinacion_Pu, rm.Pu = max(((c, -f[a]["P"]) for c, f in grav.items()), key=lambda x: x[1])
            art = "ec. 6.4.1.1" if rm.modalidad == "confinada" else "ec. 7.3.1.1"
            rm.comprobaciones.append(Comprobacion("Carga vertical", art, rm.Pu <= rm.PR, rm.Pu, rm.PR, "kN",
                                                  f"Pu de «{rm.combinacion_Pu}»; {rm.origen_FE}", True))

        # --- cortante (6.5, 7.4) ----------------------------------------------------------
        rm.d = rm.L + (ref.castillo_h / 2 if rm.modalidad != "no_reforzada" else 0.0)
        rm.Mo = ref.castillo_As * ref.castillo_fy * rm.L if rm.modalidad != "no_reforzada" else 0.0
        if sismo and g_sis is not None and a in sismo:
            Pg = -g_sis[a]["P"]  # compresión (+) sin factorizar
            Ps, Vs, Ms = sismo[a]["P"], sismo[a]["V"], sismo[a]["M"]
            rm.P_cortante = Pg - Ps
            cortante_resistente(rm, prop, ref)
            rm.Vu = FC * Vs
            art = "6.5" if rm.modalidad != "reforzada_interior" else "7.4"
            rm.comprobaciones.append(Comprobacion(
                "Cortante", art, rm.Vu <= rm.VR, rm.Vu, rm.VR, "kN",
                f"VmR = {rm.VmR:.1f} + VsR = {rm.VsR:.1f} kN; P = {rm.P_cortante:.1f} kN (CM + CVa − sismo, sin FC)", True))
            # --- flexocompresión (6.4.2.2, 7.3.2.2) ------------------------------------
            rm.Mu = FC * Ms
            casos = [(FC * (Pg + Ps), "máxima compresión"), (crit.fc_favorable * Pg - FC * Ps, "mínima compresión")]
            peor = None
            for Pu, nombre in casos:
                MR, origen = momento_resistente(Pu, rm.PR, rm.Mo, rm.d, As_total * ref.castillo_fy)
                r = rm.Mu / MR if MR > 0 else math.inf
                if peor is None or r > peor[0]:
                    peor = (r, Pu, MR, f"{nombre}, {origen}")
            _, rm.Pu_flexion, rm.MR, rm.origen_flexion = peor
            art = "6.4.2.2" if rm.modalidad != "reforzada_interior" else "7.3.2.2"
            rm.comprobaciones.append(Comprobacion(
                "Flexocompresión en el plano", art, rm.Mu <= rm.MR, rm.Mu, rm.MR, "kN·m",
                f"Pu = {rm.Pu_flexion:.1f} kN ({rm.origen_flexion}); Mo = {rm.Mo:.1f} kN·m, d = {rm.d:.2f} m", True))
        elif sismo is None and grav:
            # Sin sismo: flexocompresión con las combinaciones de gravedad
            peor = None
            for c, f in grav.items():
                Pu, Mu = -f[a]["P"], abs(f[a]["M"])
                MR, origen = momento_resistente(Pu, rm.PR, rm.Mo, rm.d, As_total * ref.castillo_fy)
                r = Mu / MR if MR > 0 else (math.inf if Mu > 0 else 0)
                if peor is None or r > peor[0]:
                    peor = (r, Pu, Mu, MR, f"«{c}», {origen}")
            _, rm.Pu_flexion, rm.Mu, rm.MR, rm.origen_flexion = peor
            rm.comprobaciones.append(Comprobacion(
                "Flexocompresión en el plano", "6.4.2.2", rm.Mu <= rm.MR, rm.Mu, rm.MR, "kN·m", rm.origen_flexion, True))

        rm.comprobaciones = _requisitos(rm, prop, ref, cs, hay_losa_10, modelados) + rm.comprobaciones
        out.muros.append(rm)

    # --- sistema y Q (4.1.13) -------------------------------------------------------------
    niveles = sorted({round(m.z, 3) for m in out.muros})
    out.niveles = len(niveles)
    modalidades = [m.modalidad for m in out.muros]
    modalidad = min(set(modalidades), key=lambda x: ("no_reforzada", "reforzada_interior", "confinada").index(x))
    hueca = any(propiedades(modelo, m.material)[0].hueca for m in out.muros)
    out.sistema = N.sistema_sismico(modalidad, hueca, con_refuerzo and all(m.ph_fyh > 0 for m in out.muros))
    out.Q = DISTORSIONES_LIMITE[out.sistema][1]
    if out.niveles > N.NIVELES_REDUCCION_Q:
        out.Q = max(1.0, out.Q - N.REDUCCION_Q)
    if modelo.espectro is not None and out.con_sismo:
        out.avisos.append(f"El espectro del modelo usa Q′R′ = {modelo.espectro.reduccion:g}; para {DISTORSIONES_LIMITE[out.sistema][0].lower()} "
                          f"la NTC da Q = {out.Q:g} (4.1.13 y NTC Sismo tabla 4.3.3). Verificar Q′ y R′ del espectro.")

    # --- agrietamiento en el análisis (3.1.1.2) ------------------------------------------
    inferiores = niveles[:1] if len(niveles) <= 3 else niveles[:2]
    sin = sorted({m.seccion for m in out.muros if round(m.z, 3) in inferiores
                  and modelo.seccion_area(m.seccion).mod_cortante > N.REDUCCION_G_AGRIETADO + 1e-9})
    if sin:
        out.avisos.append("NTC Mampostería 3.1.1.2: los muros del " + ("primer nivel" if len(inferiores) == 1 else
                          "primer y segundo nivel") + " se analizan agrietados (0.5·Gm). Las secciones " +
                          ", ".join(f"«{x}»" for x in sin) + " no tienen mod_cortante = 0.5.")

    # --- cortante de entrepiso (4.1.10 a 4.1.12) ----------------------------------------
    if out.con_sismo and respuestas and revision is not None:
        out.entrepisos = _cortante_entrepiso(modelo, out, respuestas, revision, g_sis, FC)
    return out


def _cortante_entrepiso(modelo, out: RevisionMamposteria, respuestas, revision, g_sis, FC) -> list[CortanteEntrepiso]:
    res = []
    por_z: dict[float, list[RevisionMuro]] = {}
    for m in out.muros:
        por_z.setdefault(round(m.z, 3), []).append(m)
    for z, muros in sorted(por_z.items()):
        z_tope = max(m.z + m.H for m in muros)
        AT_total = sum(m.AT for m in muros)
        peso = sum(-g_sis[m.muro]["P"] for m in muros)
        for d in ("X", "Y"):
            r = respuestas.get(d)
            if r is None or not r.cortantes_entrepiso:
                continue
            en_d = [m for m in muros if m.direccion == d]
            if not en_d:
                continue
            nivel = min(r.cortantes_entrepiso, key=lambda x: abs(x[0] - z_tope))
            if abs(nivel[0] - z_tope) > 0.05:
                continue
            a_dis = revision.cortante[d].V0 / r.cortante_basal if r.cortante_basal else 1.0
            Vu = FC * revision.escala.get(d, 1.0) * a_dis * nivel[1]
            VR = 0.0
            sigma_prom = peso / AT_total if AT_total > 0 else 0.0
            sig = sigma_prom
            for m in en_d:
                prop, _ = propiedades(modelo, m.material)
                sig = min(sigma_prom, N.SIGMA_MAX_ENTREPISO * prop.vm)
                VR += N.FR_CORTANTE * (0.5 * prop.vm + 0.3 * sig + m.eta * m.ph_fyh_e) * m.AT
            res.append(CortanteEntrepiso(d, z, z_tope, [m.muro for m in en_d], sum(m.AT for m in en_d), sig, VR, Vu))
    return res
