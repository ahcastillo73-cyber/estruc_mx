"""Corre los análisis que necesita el reporte y guarda todo en un solo objeto.

Las secciones solo leen de `DatosReporte`; no analizan nada. Así se pueden probar con
datos fijos y la ventana podrá reutilizar resultados que ya tenga en memoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import __version__
from ..analisis.espectral import PropiedadesModales, RespuestaEspectral, espectral, propiedades_modales
from ..analisis.revision_sismica import CriteriosSismicos, RevisionSismica, revisar
from ..modelo import Edificio, masas_nodales
from ..motores import Modos, Resultados
from ..normas.ntc_sismo import DISTORSION_SERVICIO, DISTORSIONES_LIMITE


@dataclass
class Opciones:
    motor: str = "pynite"
    n_modos: int = 12
    metodo: str = "CQC"
    # Sistema estructural de `normas.ntc_sismo.DISTORSIONES_LIMITE`, o límite explícito
    sistema: str | None = None
    deriva_limite: float | None = None
    # Factor que convierte la deriva calculada en la que se compara (Q·R de las NTC);
    # None = la reducción del espectro
    factor_deriva: float | None = None
    # Revisión sísmica (analisis/revision_sismica.py)
    norma: str = "NTC"  # "NTC" o "CFE"
    grupo: str = "B"  # A: Ocupación Inmediata; B: Limitación de Daño No Estructural
    zona: str | None = None  # zona sísmica A, B o C, para Ks
    periodo_sitio: float | None = None  # Ts, s
    sobrerresistencia: float = 1.0  # R′ que divide a a_min
    cortante_minimo: float | None = None  # coeficiente explícito, fracción de W
    escalar_desplazamientos: bool = False
    torsion: bool = True
    excentricidad: float | None = None  # fracción de b; None = la de la norma
    divisor_servicio: float | None = None  # si el modelo no tiene espectro de servicio
    limite_servicio: float = DISTORSION_SERVICIO
    autor: str = ""
    fecha: str = field(default_factory=lambda: date.today().isoformat())

    def limite(self) -> tuple[float | None, str]:
        """Distorsión límite y de dónde sale."""
        if self.deriva_limite is not None:
            return self.deriva_limite, "indicada por el usuario"
        if self.sistema:
            desc, _, valor, _ = DISTORSIONES_LIMITE[self.sistema]
            return valor, f"γSV de las NTC Sismo 2023, {desc[0].lower() + desc[1:]}"
        return None, ""

    def limite_oi(self) -> tuple[float | None, str]:
        """γOI para Ocupación Inmediata (Grupo A)."""
        if self.sistema:
            desc, _, _, valor = DISTORSIONES_LIMITE[self.sistema]
            return valor, f"γOI de las NTC Sismo 2023, {desc[0].lower() + desc[1:]}"
        return None, ""

    def criterios(self) -> CriteriosSismicos:
        return CriteriosSismicos(
            norma=self.norma, factor_qr=self.factor_deriva, periodo_sitio=self.periodo_sitio,
            sobrerresistencia=self.sobrerresistencia, cortante_minimo=self.cortante_minimo,
            escalar_desplazamientos=self.escalar_desplazamientos, torsion=self.torsion,
            excentricidad=self.excentricidad, zona=self.zona, divisor_servicio=self.divisor_servicio,
            limite_servicio=self.limite_servicio,
        )


@dataclass
class DatosReporte:
    modelo: Edificio
    opciones: Opciones
    version: str = __version__
    estatico: Resultados | None = None
    modos: Modos | None = None
    propiedades: PropiedadesModales | None = None
    espectral: dict[str, RespuestaEspectral] = field(default_factory=dict)  # "X", "Y"
    revision: RevisionSismica | None = None
    mamposteria: object | None = None  # diseno.mamposteria.RevisionMamposteria
    masas: dict[str, float] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)  # lo que no se pudo calcular

    @property
    def factor_deriva(self) -> float:
        if self.opciones.factor_deriva is not None:
            return self.opciones.factor_deriva
        e = self.modelo.espectro
        return e.reduccion if e is not None else 1.0


def _motor(nombre: str):
    if nombre == "pynite":
        from ..motores import pynite

        return pynite
    from ..motores import opensees

    return opensees


def preparar(modelo: Edificio, opciones: Opciones | None = None) -> DatosReporte:
    """Corre el análisis estático, el modal y el espectral en X y Y con el motor elegido."""
    op = opciones or Opciones()
    if op.grupo not in ("A", "B"):
        raise ValueError(f"grupo '{op.grupo}' desconocido; opciones: A, B")
    if op.norma not in ("NTC", "CFE"):
        raise ValueError(f"norma '{op.norma}' desconocida; opciones: NTC, CFE")
    if op.sistema and op.sistema not in DISTORSIONES_LIMITE:
        raise ValueError(f"sistema '{op.sistema}' desconocido; opciones: {', '.join(DISTORSIONES_LIMITE)}")
    d = DatosReporte(modelo=modelo, opciones=op)
    motor = _motor(op.motor)
    if modelo.areas:
        from ..modelo.malla import discretizar

        d.avisos += discretizar(modelo).avisos

    if modelo.patrones:
        d.estatico = motor.analizar(modelo)

    try:
        d.masas = masas_nodales(modelo)
    except ValueError as e:
        d.avisos.append(f"No se calcularon las masas: {e}")
    if not d.masas:
        d.avisos.append("El modelo no tiene masa: no hay análisis modal ni espectral.")
    else:
        d.modos = motor.modal(modelo, op.n_modos)
        d.propiedades = propiedades_modales(modelo, d.modos)
        if modelo.espectro is None:
            d.avisos.append("El modelo no tiene espectro: no hay análisis espectral.")
        else:
            for direccion in ("X", "Y"):
                d.espectral[direccion] = espectral(modelo, d.modos, direccion, op.metodo)
            d.revision = revisar(modelo, d.modos, d.espectral, motor, op.criterios())
    _mamposteria(d, motor)
    return d


def _mamposteria(d: DatosReporte, motor) -> None:
    from ..diseno.mamposteria import muros_de_mamposteria, revisar_mamposteria

    if muros_de_mamposteria(d.modelo):
        d.mamposteria = revisar_mamposteria(d.modelo, d.estatico, d.revision, d.espectral or None, motor)
