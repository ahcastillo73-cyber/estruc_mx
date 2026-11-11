"""Revisión sísmica sobre los resultados del análisis modal espectral (NTC Sismo / CFE).

Toma las respuestas espectrales en X y en Y y añade lo que piden las normas:

1. Cortante basal mínimo: si el cortante de diseño V0 es menor que el mínimo, se calcula un
   factor de escala para las fuerzas de diseño (NTC 2020, 1.7: los desplazamientos no se
   escalan; opcionalmente también se escalan).
2. Torsión accidental (NTC 2023, 2.3): en cada nivel se aplica el momento M0i = Mai − Ma(i+1),
   con Mai = Vi·eai, Vi el cortante del entrepiso i del análisis modal y eai la excentricidad
   accidental medida perpendicularmente al sismo. Se resuelve como caso estático con el mismo
   motor y su efecto se suma, con el signo más desfavorable, al del análisis modal (que ya
   incluye la torsión natural por usar el modelo tridimensional).
3. Componentes ortogonales: 100 % del sismo en una dirección más 30 % del perpendicular, y la
   envolvente de las dos combinaciones.
4. Distorsiones (1.7) para Seguridad de Vida, Ocupación Inmediata y Limitación de Daño, con
   torsión y 100/30.

Sin diafragma rígido el momento torsionante se reparte a los nodos del modelo en el piso,
proporcional a su masa y a su distancia al centro de masa (rotación de cuerpo rígido); con
diafragma flexible esta distribución es una aproximación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ..modelo import CargaNodal, Combinacion, Edificio, PatronCarga, masas_nodales
from ..modelo.malla import discretizar
from ..modelo.masas import G
from ..motores import Modos
from ..normas import cfe_sismo, ntc_sismo
from .areas import COMPONENTES_MURO, todas_fuerzas_muros
from .espectral import RespuestaEspectral, elementos_verticales, espectral
from .pisos import Piso, pisos

DIRECCIONES = ("X", "Y")
_OTRA = {"X": "Y", "Y": "X"}


@dataclass
class CriteriosSismicos:
    norma: Literal["NTC", "CFE"] = "NTC"
    # Factor que convierte la respuesta calculada en la de diseño sin reducir (Q·R de las NTC):
    # V0 de diseño = V calculado · reducción del espectro / factor; None = la reducción del espectro
    factor_qr: float | None = None
    periodo_sitio: float | None = None  # Ts, s (NTC); sin él se toma el a_min mayor
    sobrerresistencia: float = 1.0  # R con que se divide a_min (NTC)
    cortante_minimo: float | None = None  # coeficiente explícito (fracción de W); reemplaza el de la norma
    escalar_desplazamientos: bool = False
    torsion: bool = True
    excentricidad: float | None = None  # fracción de b fija en todos los pisos; None = la de la norma
    ortogonal: float = ntc_sismo.FACTOR_ORTOGONAL
    # Limitación de Daño: espectro elástico × Ks de la zona (A, B o C; B necesita Ts). Si el
    # modelo tiene `espectro_servicio`, se usa ese; si se da el divisor, elástico / divisor.
    zona: str | None = None
    divisor_servicio: float | None = None
    limite_servicio: float = ntc_sismo.DISTORSION_SERVICIO


@dataclass
class CortanteMinimo:
    direccion: str
    V0: float  # cortante basal de diseño del análisis modal, kN
    W: float  # peso sísmico, kN
    coeficiente: float  # mínimo, fracción de W
    origen: str
    T1: float  # periodo del modo dominante en la dirección, s

    @property
    def Vmin(self) -> float:
        return self.coeficiente * self.W

    @property
    def factor(self) -> float:
        """Factor de escala de las fuerzas de diseño (1 si V0 ya alcanza el mínimo)."""
        return max(1.0, self.Vmin / self.V0) if self.V0 > 0 else 1.0


@dataclass
class TorsionPiso:
    z: float
    xc: float
    yc: float
    b: float  # dimensión perpendicular al sismo, m
    fraccion: float  # e_a / b
    V: float  # cortante del entrepiso de abajo del nivel, kN (sin escalar)
    M0: float = 0.0  # momento aplicado en el nivel, Ma(i) − Ma(i+1), kN·m

    @property
    def e(self) -> float:
        return self.fraccion * self.b

    @property
    def Ma(self) -> float:
        """Momento torsionante de entrepiso, V·e_a."""
        return self.V * self.e


@dataclass
class DerivaNivel:
    nivel: float
    deriva: float  # calculada (sin multiplicar por Q·R)
    elemento: str
    gobierna: str  # combinación que gobierna, p. ej. "X + 0.3Y"


@dataclass
class RevisionSismica:
    criterios: CriteriosSismicos
    cortante: dict[str, CortanteMinimo]
    pisos: list[Piso]
    torsion: dict[str, list[TorsionPiso]] = field(default_factory=dict)
    # componente ("X", "Y") -> máxima por nivel, con torsión y componentes ortogonales
    derivas: dict[str, list[DerivaNivel]] = field(default_factory=dict)
    # Igual que `derivas` pero ya en términos de servicio (comparables con el límite de servicio)
    derivas_servicio: dict[str, list[DerivaNivel]] = field(default_factory=dict)
    origen_servicio: str = ""
    # Con el espectro elástico (Ocupación Inmediata, Grupo A)
    derivas_elasticas: dict[str, list[DerivaNivel]] = field(default_factory=dict)
    # muro -> fuerzas sísmicas de diseño (escaladas, con torsión y 100/30), valores positivos
    fuerzas_muros: dict[str, dict[str, float]] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


def _factor_qr(modelo: Edificio, c: CriteriosSismicos) -> float:
    if c.factor_qr is not None:
        return c.factor_qr
    return modelo.espectro.reduccion if modelo.espectro is not None else 1.0


def _periodo_dominante(r: RespuestaEspectral) -> float:
    p = r.propiedades
    i = int(np.argmax(p.fraccion_masa[r.direccion]))
    return p.periodos[i]


def cortante_minimo(modelo: Edificio, r: RespuestaEspectral, W: float, c: CriteriosSismicos) -> CortanteMinimo:
    a_diseno = modelo.espectro.reduccion / _factor_qr(modelo, c)  # respuesta calculada -> de diseño
    V0 = r.cortante_basal * a_diseno
    T1 = _periodo_dominante(r)
    if c.cortante_minimo is not None:
        coef, origen = c.cortante_minimo, "indicado por el usuario"
    elif c.norma == "CFE":
        coef = cfe_sismo.FACTOR_CORTANTE_MINIMO * modelo.espectro.sa(T1) * a_diseno
        origen = f"CFE: {cfe_sismo.FACTOR_CORTANTE_MINIMO:g}·a(T1)/(Q′R), T1 = {T1:.3f} s"
    else:
        coef = ntc_sismo.a_min(c.periodo_sitio, c.sobrerresistencia)
        ts = f"Ts = {c.periodo_sitio:g} s" if c.periodo_sitio is not None else "sin Ts, se toma el mayor"
        origen = f"NTC: a_min = {coef * c.sobrerresistencia:.3f}/R, R = {c.sobrerresistencia:g}, {ts}"
    return CortanteMinimo(r.direccion, V0, W, coef, origen, T1)


def _torsion_pisos(lista: list[Piso], r: RespuestaEspectral, c: CriteriosSismicos) -> list[TorsionPiso]:
    n = len(lista)
    regla = cfe_sismo.excentricidad_accidental if c.norma == "CFE" else ntc_sismo.excentricidad_accidental
    out = []
    for i, (p, (_, V)) in enumerate(zip(lista, r.cortantes_entrepiso), start=1):
        frac = c.excentricidad if c.excentricidad is not None else regla(i, n)
        b = p.by if r.direccion == "X" else p.bx
        out.append(TorsionPiso(z=p.z, xc=p.xc, yc=p.yc, b=b, fraccion=frac, V=V))
    # Ec. 2.3.3: el momento en cada nivel es la diferencia de los de entrepiso
    for k, t in enumerate(out):
        t.M0 = t.Ma - (out[k + 1].Ma if k + 1 < len(out) else 0.0)
    return out


def cargas_torsion(modelo: Edificio, lista: list[Piso], torsion: list[TorsionPiso],
                   masas: dict[str, float], patron: str) -> list[CargaNodal]:
    """Momento M0 de cada piso.

    Con diafragma rígido, un momento MZ en un nodo del piso: el diafragma lo lleva al maestro
    igual que si se aplicara en él (el maestro no es un nodo del modelo, así que no puede llevar
    cargas). Sin diafragma, un par de fuerzas horizontales en los nodos del modelo del piso,
    proporcional a su masa y a su distancia al centro de masa."""
    del_modelo = {n.id for n in modelo.nodos}
    cargas = []
    for p, t in zip(lista, torsion):
        nodos = [n for n in p.nodos if n in del_modelo]
        if not nodos or t.M0 == 0:
            continue
        if p.diafragma is not None:
            esclavos = [n for n in p.diafragma.esclavos if n in del_modelo]
            if esclavos:
                n = min(esclavos, key=lambda n: (modelo.nodo(n).x - t.xc) ** 2 + (modelo.nodo(n).y - t.yc) ** 2)
                cargas.append(CargaNodal(patron=patron, nodo=n, fuerzas=(0, 0, 0, 0, 0, t.M0)))
                continue
        xy = np.array([[modelo.nodo(n).x - t.xc, modelo.nodo(n).y - t.yc] for n in nodos])
        w = np.array([masas.get(n, 0.0) for n in nodos])
        if w.sum() <= 0:
            w = np.ones(len(nodos))
        J = float(np.sum(w * np.sum(xy**2, axis=1)))
        if J <= 1e-12:
            cargas.append(CargaNodal(patron=patron, nodo=nodos[0], fuerzas=(0, 0, 0, 0, 0, t.M0)))
            continue
        k = t.M0 / J
        for n, (dx, dy), wi in zip(nodos, xy, w):
            if wi:
                cargas.append(CargaNodal(patron=patron, nodo=n, fuerzas=(-k * wi * dy, k * wi * dx, 0, 0, 0, 0)))
    return cargas


def _modelo_torsion(modelo: Edificio, cargas: dict[str, list[CargaNodal]]) -> Edificio:
    m = modelo.model_copy(deep=True)
    m.patrones = [PatronCarga(nombre=p, tipo="sismo") for p in cargas]
    m.cargas_nodales = [c for lista in cargas.values() for c in lista]
    m.cargas_distribuidas, m.cargas_area = [], []
    m.combinaciones = [Combinacion(nombre=p, factores={p: 1.0}) for p in cargas]
    return m


def _derivas_estaticas(modelo: Edificio, desplazamientos: dict[str, list[float]]) -> list[dict[str, float]]:
    """Distorsión (valor absoluto) de cada tramo vertical, en el orden de `elementos_verticales`."""
    out = []
    for _, abajo, arriba in elementos_verticales(modelo):
        h = arriba.z - abajo.z
        ua, ub = desplazamientos[arriba.id], desplazamientos[abajo.id]
        out.append({"X": abs(ua[0] - ub[0]) / h, "Y": abs(ua[1] - ub[1]) / h})
    return out


def _envolvente(por_sismo: dict[str, list[dict[str, float]]], elementos, ortogonal: float) -> dict[str, list[DerivaNivel]]:
    """Máxima por nivel de cada componente con 100 % de un sismo + `ortogonal` del otro."""
    out: dict[str, list[DerivaNivel]] = {}
    for comp in DIRECCIONES:
        por_nivel: dict[float, DerivaNivel] = {}
        for k, e in enumerate(elementos):
            for d in DIRECCIONES:
                v = float(por_sismo[d][k][comp] + ortogonal * por_sismo[_OTRA[d]][k][comp])
                if e.nivel not in por_nivel or v > por_nivel[e.nivel].deriva:
                    por_nivel[e.nivel] = DerivaNivel(e.nivel, v, e.elemento, f"{d} + {ortogonal:g}{_OTRA[d]}")
        out[comp] = [por_nivel[z] for z in sorted(por_nivel)]
    return out


def revisar(modelo: Edificio, modos: Modos, respuestas: dict[str, RespuestaEspectral], motor,
            criterios: CriteriosSismicos | None = None) -> RevisionSismica:
    """`respuestas` son las espectrales en X y Y; `motor` el módulo que resuelve la torsión."""
    c = criterios or CriteriosSismicos()
    if set(respuestas) != set(DIRECCIONES):
        raise ValueError("se necesitan las respuestas espectrales en X y en Y")
    malla = discretizar(modelo)
    masas = masas_nodales(modelo, malla)
    W = sum(masas.values()) * G
    lista = pisos(modelo, malla, masas)
    rev = RevisionSismica(criterios=c, cortante={}, pisos=lista)
    for d, r in respuestas.items():
        rev.cortante[d] = cortante_minimo(modelo, r, W, c)
    escala = {d: rev.cortante[d].factor for d in DIRECCIONES}
    escala_desp = {d: escala[d] if c.escalar_desplazamientos else 1.0 for d in DIRECCIONES}

    # --- torsión accidental -------------------------------------------------------
    elementos = respuestas["X"].derivas_elementos
    tors_derivas = {d: [{"X": 0.0, "Y": 0.0} for _ in elementos] for d in DIRECCIONES}
    tors_muros: dict[str, dict[str, dict[str, float]]] = {}
    if c.torsion and lista:
        rev.torsion = {d: _torsion_pisos(lista, respuestas[d], c) for d in DIRECCIONES}
        cargas = {f"TA{d}": cargas_torsion(modelo, lista, rev.torsion[d], masas, f"TA{d}") for d in DIRECCIONES}
        cargas = {p: v for p, v in cargas.items() if v}
        if cargas:
            res = motor.analizar(_modelo_torsion(modelo, cargas))
            for d in DIRECCIONES:
                if f"TA{d}" in res.desplazamientos:
                    tors_derivas[d] = _derivas_estaticas(modelo, res.desplazamientos[f"TA{d}"])
                    if any(a.tipo == "muro" for a in modelo.areas):
                        tors_muros[d] = todas_fuerzas_muros(modelo, malla, res.fuerzas_elementos.get(f"TA{d}", {}))
            sin = [f"{p.z:g}" for p in lista if p.diafragma is None]
            if sin:
                rev.avisos.append(f"Niveles sin diafragma rígido ({', '.join(sin)} m): la torsión accidental se "
                                  "reparte a sus nodos como rotación de cuerpo rígido, que es una aproximación.")

    # --- distorsiones con torsión y componentes ortogonales ----------------------
    por_sismo = {
        d: [{k: escala_desp[d] * e.componentes[k] + escala_desp[d] * t[k] for k in DIRECCIONES}
            for e, t in zip(respuestas[d].derivas_elementos, tors_derivas[d])]
        for d in DIRECCIONES
    }
    rev.derivas = _envolvente(por_sismo, elementos, c.ortogonal)

    # --- Ocupación Inmediata y Limitación de Daño (espectro elástico) ------------
    # La distorsión elástica es la calculada por la reducción del espectro de diseño; la torsión,
    # que sale de los mismos cortantes, se escala igual.
    red = modelo.espectro.reduccion
    elastica = _envolvente({d: [{k: red * (e.componentes[k] + t[k]) for k in DIRECCIONES}
                                for e, t in zip(respuestas[d].derivas_elementos, tors_derivas[d])]
                            for d in DIRECCIONES}, elementos, c.ortogonal)
    rev.derivas_elasticas = elastica
    if modelo.espectro_servicio is not None:
        serv = {d: espectral(modelo, modos, d, respuestas[d].metodo, espectro=modelo.espectro_servicio)
                for d in DIRECCIONES}
        # La torsión de servicio se toma proporcional al cortante basal de cada espectro
        rel = {d: serv[d].cortante_basal / respuestas[d].cortante_basal if respuestas[d].cortante_basal else 0.0
               for d in DIRECCIONES}
        ps = {d: [{k: e.componentes[k] + rel[d] * t[k] for k in DIRECCIONES}
                  for e, t in zip(serv[d].derivas_elementos, tors_derivas[d])] for d in DIRECCIONES}
        rev.derivas_servicio = _envolvente(ps, elementos, c.ortogonal)
        rev.origen_servicio = f"espectro de servicio «{modelo.espectro_servicio.nombre}» del modelo"
    else:
        f = None
        if c.divisor_servicio:
            f, rev.origen_servicio = 1 / c.divisor_servicio, f"espectro elástico dividido entre {c.divisor_servicio:g}"
        elif c.zona:
            f = ntc_sismo.ks(c.zona, c.periodo_sitio)
            ts = f", Ts = {c.periodo_sitio:g} s" if c.zona.upper() == "B" else ""
            rev.origen_servicio = f"espectro elástico por Ks = {f:.4f} (zona {c.zona.upper()}{ts}, ec. 3.1.1)"
        if f is not None:
            rev.derivas_servicio = {k: [DerivaNivel(x.nivel, x.deriva * f, x.elemento, x.gobierna) for x in v]
                                    for k, v in elastica.items()}

    # --- fuerzas de diseño en muros ----------------------------------------------
    if all(respuestas[d].fuerzas_muros for d in DIRECCIONES):
        por_d = {}
        for d in DIRECCIONES:
            t = tors_muros.get(d, {})
            por_d[d] = {a: {k: escala[d] * (v + abs(t.get(a, {}).get(k, 0.0))) for k, v in f.items()}
                        for a, f in respuestas[d].fuerzas_muros.items()}
        rev.fuerzas_muros = {
            a: {k: float(max(por_d[d][a][k] + c.ortogonal * por_d[_OTRA[d]][a][k] for d in DIRECCIONES))
                for k in COMPONENTES_MURO}
            for a in por_d["X"]
        }
    return rev
