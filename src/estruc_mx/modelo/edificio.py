"""Modelo de datos del edificio: la fuente única de verdad.

Unidades: kN, m, s. Los esfuerzos y módulos van en kPa (kN/m²).
Ejes globales: X y Y horizontales, Z vertical hacia arriba (convención tipo ETABS).

Muros y losas (`Area`) son cuadriláteros planos de cuatro nodos, dados en orden alrededor del
perímetro. Los motores los dividen en elementos de cáscara (ver modelo/malla.py).

Ejes locales de una barra (1, 2, 3 en ETABS; x, y, z aquí):
- x va del nodo i al nodo j.
- Barras no verticales: z es horizontal y perpendicular a x; y tiene componente hacia arriba.
  La flexión mayor (I33) es alrededor de z, así que resiste la gravedad en vigas.
- Barras verticales que suben: y = -X global, z = -Y global.
`rotacion` (grados) gira y, z alrededor de x.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

import numpy as np
from pydantic import BaseModel, Field, model_validator

from .espectro import Espectro


# NTC Mampostería 2023, ec. 2.8.6.4.1: Gm = 0.2·Em cuando Em sale de 2.8.5.4
RELACION_G_MAMPOSTERIA = 0.2


class PropiedadesMamposteria(BaseModel):
    """Datos de diseño de la mampostería (NTC Mampostería 2023, capítulo 2). Esfuerzos en kPa.

    f'm y v'm son de diseño, sobre área bruta: de ensayes de pilas y muretes (2.8.1.3, 2.8.2.4)
    o de las tablas de la norma (ver `normas/ntc_mamposteria.py`)."""

    pieza: Literal[
        "tabique_arcilla_artesanal", "tabique_arcilla_extruido", "bloque_concreto", "tabicon_concreto",
        "otra_arcilla", "otra_concreto",
    ] = "tabique_arcilla_artesanal"
    hueca: bool = Field(False, description="Pieza hueca (área neta/bruta < 0.75, tabla 2.1.1.2)")
    fan: float = Field(1.0, gt=0, le=1.0, description="Área neta / área bruta de la pieza")
    mortero: Literal["I", "II"] = "I"
    fp: float | None = Field(None, gt=0, description="f'p de diseño de la pieza, kPa (opcional, solo informativo)")
    fm: float = Field(gt=0, description="f'm, resistencia de diseño a compresión, kPa")
    vm: float = Field(gt=0, description="v'm, resistencia de diseño a compresión diagonal, kPa")

    @property
    def de_concreto(self) -> bool:
        return self.pieza in ("bloque_concreto", "tabicon_concreto", "otra_concreto")


class Material(BaseModel):
    nombre: str
    tipo: Literal["concreto", "acero", "mamposteria", "generico"] = "generico"
    E: float = Field(gt=0, description="Módulo de elasticidad, kPa")
    nu: float = Field(0.2, ge=0, lt=0.5, description="Relación de Poisson")
    peso_vol: float = Field(0.0, ge=0, description="Peso volumétrico, kN/m³")
    G_cortante: float | None = Field(
        None, gt=0,
        description="Módulo de cortante explícito, kPa. Sin él: 0.2·E en mampostería (NTC Mampostería "
                    "2.8.6.4.1) y E/(2(1 + ν)) en los demás materiales",
    )
    mamposteria: PropiedadesMamposteria | None = None

    @property
    def G(self) -> float:
        if self.G_cortante is not None:
            return self.G_cortante
        if self.tipo == "mamposteria":
            return RELACION_G_MAMPOSTERIA * self.E
        return self.E / (2.0 * (1.0 + self.nu))

    @property
    def G_isotropo(self) -> float:
        return self.E / (2.0 * (1.0 + self.nu))


class _SeccionBase(BaseModel):
    nombre: str
    material: str


class SeccionRectangular(_SeccionBase):
    forma: Literal["rectangular"] = "rectangular"
    b: float = Field(gt=0, description="Ancho, paralelo al eje local z, m")
    h: float = Field(gt=0, description="Peralte, paralelo al eje local y, m")

    @property
    def A(self) -> float:
        return self.b * self.h

    @property
    def I33(self) -> float:
        return self.b * self.h**3 / 12.0

    @property
    def I22(self) -> float:
        return self.h * self.b**3 / 12.0

    @property
    def J(self) -> float:
        a, c = max(self.b, self.h), min(self.b, self.h)
        return a * c**3 * (1.0 / 3.0 - 0.21 * (c / a) * (1.0 - c**4 / (12.0 * a**4)))


class SeccionGeneral(_SeccionBase):
    forma: Literal["general"] = "general"
    A: float = Field(gt=0)
    I33: float = Field(gt=0, description="Inercia mayor, alrededor del eje local z")
    I22: float = Field(gt=0, description="Inercia menor, alrededor del eje local y")
    J: float = Field(gt=0)


Seccion = Annotated[Union[SeccionRectangular, SeccionGeneral], Field(discriminator="forma")]


class RefuerzoMuroMamposteria(BaseModel):
    """Modalidad y refuerzo de un muro de mampostería (NTC Mampostería 2023, capítulos 6 y 7).

    Unidades del modelo: m, m², kPa. Los castillos se suponen en los extremos del muro y en las
    intersecciones (6.2.1.1), con los intermedios que pida la separación máxima."""

    modalidad: Literal["confinada", "reforzada_interior", "no_reforzada"] = "confinada"
    # Castillos (o refuerzo vertical de extremo en muros reforzados interiormente)
    castillo_b: float = Field(0.15, gt=0, description="bc, dimensión perpendicular al muro, m")
    castillo_h: float = Field(0.15, gt=0, description="hc, dimensión paralela al muro, m")
    castillo_As: float = Field(2.85e-4, ge=0, description="Acero longitudinal de un castillo, m² (4 #3 = 2.85 cm²)")
    castillo_barras: int = Field(4, ge=0, description="Número de barras longitudinales del castillo")
    castillo_fy: float = Field(412e3, gt=0, description="fy del acero longitudinal, kPa")
    castillo_fc: float = Field(20e3, gt=0, description="f'c del concreto de castillos y dalas, kPa")
    estribo_Asc: float = Field(0.62e-4, ge=0, description="Asc, área de las dos ramas del estribo, m²")
    estribo_fy: float = Field(412e3, gt=0, description="fy de los estribos, kPa")
    estribo_s: float = Field(0.20, gt=0, description="Separación de estribos en el tramo central, m")
    estribo_s_extremo: float = Field(0.075, gt=0, description="Separación de estribos en los extremos (Ho), m")
    # Dalas
    dala_b: float = Field(0.15, gt=0, description="Ancho de la dala, m")
    dala_h: float = Field(0.20, gt=0, description="Peralte de la dala, m (o el de la losa si es de 10 cm o más)")
    # Refuerzo horizontal en las juntas
    Ash: float = Field(0.0, ge=0, description="Área de refuerzo horizontal por junta reforzada, m²")
    sh: float = Field(0.0, ge=0, description="Separación vertical del refuerzo horizontal, m (0 = sin refuerzo)")
    fyh: float = Field(412e3, gt=0, description="fyh del refuerzo horizontal, kPa (≤ 600 MPa)")
    junta: float = Field(0.012, gt=0, description="hj, espesor de la junta horizontal de mortero, m")
    # Solo para muros reforzados interiormente: cuantía vertical × fy (7.1.5.1)
    pv_fyv: float = Field(0.0, ge=0, description="pv·fyv del refuerzo vertical interior, kPa")
    fnm: float = Field(1.0, gt=0, le=1.0, description="Área neta / bruta del muro reforzado interiormente (7.4.3.3)")

    def ph_fyh(self, t: float) -> float:
        """ph·fyh (kPa) con ph = Ash/(sh·t), ec. 6.5.3.4.1.b; 0 sin refuerzo horizontal."""
        if self.sh <= 0 or self.Ash <= 0:
            return 0.0
        return self.Ash / (self.sh * t) * self.fyh


class SeccionArea(BaseModel):
    """Sección de muro o losa: material y espesor. Se analiza como cáscara elástica
    (membrana más placa)."""

    nombre: str
    material: str
    tipo: Literal["muro", "losa"] = "muro"
    espesor: float = Field(gt=0, description="m")
    mod_rigidez: float = Field(
        1.0, gt=0, le=1.0,
        description="Multiplica E en membrana y flexión, p. ej. 0.5 para muros agrietados (NTC Concreto)",
    )
    mod_cortante: float = Field(
        1.0, gt=0, le=1.0,
        description="Multiplica además el módulo de cortante en el plano, p. ej. 0.5 para muros de "
                    "mampostería agrietados (NTC Mampostería 3.1.1.2.3)",
    )
    mamposteria: RefuerzoMuroMamposteria | None = None


class Nodo(BaseModel):
    id: str
    x: float
    y: float
    z: float

    @property
    def coords(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)


class Apoyo(BaseModel):
    nodo: str
    restricciones: tuple[bool, bool, bool, bool, bool, bool] = Field(
        (True, True, True, True, True, True),
        description="UX, UY, UZ, RX, RY, RZ",
    )


class Barra(BaseModel):
    id: str
    tipo: Literal["columna", "viga", "contraviento", "barra"] = "barra"
    i: str
    j: str
    seccion: str
    rotacion: float = 0.0


class Area(BaseModel):
    """Muro o losa: cuadrilátero plano con los nodos en orden alrededor del perímetro."""

    id: str
    tipo: Literal["muro", "losa"] = "muro"
    nodos: tuple[str, str, str, str]
    seccion: str
    # Muro extremo (en el perímetro, con losa de un solo lado) para el factor FE de la NTC
    # Mampostería 3.1.2.3; None = se decide por su posición en la planta
    extremo: bool | None = None


class PatronCarga(BaseModel):
    nombre: str
    tipo: Literal["muerta", "viva", "sismo", "viento", "otra"] = "otra"
    peso_propio: float = Field(
        0.0, ge=0, description="Multiplicador del peso propio de barras, muros y losas que se aplica en este patrón"
    )


class CargaNodal(BaseModel):
    patron: str
    nodo: str
    fuerzas: tuple[float, float, float, float, float, float] = Field(
        description="FX, FY, FZ (kN), MX, MY, MZ (kN·m), en ejes globales"
    )


class CargaDistribuida(BaseModel):
    """Carga uniforme por metro de barra, en dirección global."""

    patron: str
    barra: str
    direccion: Literal["X", "Y", "Z"]
    w: float = Field(description="kN/m; negativo en Z es gravedad")


class CargaArea(BaseModel):
    """Carga uniforme por m² de superficie de un muro o losa, en dirección global."""

    patron: str
    area: str
    direccion: Literal["X", "Y", "Z"] = "Z"
    w: float = Field(description="kN/m²; negativo en Z es gravedad")


class MasaNodal(BaseModel):
    nodo: str
    masa: float = Field(gt=0, description="t (kN·s²/m), traslacional en X, Y y Z")


class Combinacion(BaseModel):
    nombre: str
    factores: dict[str, float]


class Diafragma(BaseModel):
    """Diafragma rígido horizontal a la elevación `z` (un piso con losa que no se deforma en su
    plano). Todos los nodos de la malla de análisis a esa altura se mueven juntos en X, Y y en
    el giro RZ, con un nodo maestro en el centro de masa (ver modelo/diafragmas.py). La flexión
    de la losa fuera de su plano no cambia."""

    nombre: str
    z: float = Field(description="Elevación, m")


class EjeRejilla(BaseModel):
    nombre: str
    coord: float = Field(description="Coordenada del eje, m")


class Nivel(BaseModel):
    nombre: str
    z: float = Field(description="Elevación, m")


class Rejilla(BaseModel):
    """Ejes y niveles de referencia para dibujar (como la rejilla de ETABS).

    Los ejes X son rectas paralelas a Y en x = coord; los ejes Y son paralelas a X en y = coord.
    No entra en el análisis: solo ayuda a crear nodos y barras en lugares conocidos.
    """

    ejes_x: list[EjeRejilla] = []
    ejes_y: list[EjeRejilla] = []
    niveles: list[Nivel] = []

    @model_validator(mode="after")
    def _ordenar(self) -> "Rejilla":
        self.ejes_x.sort(key=lambda e: e.coord)
        self.ejes_y.sort(key=lambda e: e.coord)
        self.niveles.sort(key=lambda n: n.z)
        for que, items in (("ejes X", self.ejes_x), ("ejes Y", self.ejes_y), ("niveles", self.niveles)):
            nombres = [i.nombre for i in items]
            if len(set(nombres)) != len(nombres):
                raise ValueError(f"rejilla: nombres de {que} repetidos")
        return self

    @classmethod
    def regular(cls, claros_x: list[float], claros_y: list[float], alturas: list[float]) -> "Rejilla":
        """Rejilla a partir de claros y alturas de entrepiso. Ejes X: A, B, C…; ejes Y: 1, 2, 3…;
        niveles: Base, N1, N2…"""

        def acumular(claros: list[float]) -> list[float]:
            c = [0.0]
            for d in claros:
                c.append(c[-1] + d)
            return c

        return cls(
            ejes_x=[EjeRejilla(nombre=_letra(k), coord=x) for k, x in enumerate(acumular(claros_x))],
            ejes_y=[EjeRejilla(nombre=str(k + 1), coord=y) for k, y in enumerate(acumular(claros_y))],
            niveles=[Nivel(nombre="Base" if k == 0 else f"N{k}", z=z) for k, z in enumerate(acumular(alturas))],
        )

    def intersecciones(self) -> list[tuple[str, tuple[float, float, float]]]:
        """Puntos (nombre, (x, y, z)) en cada cruce de ejes y nivel, p. ej. ("B2-N1", (6, 5, 3.5))."""
        return [
            (f"{ex.nombre}{ey.nombre}-{nv.nombre}", (ex.coord, ey.coord, nv.z))
            for nv in self.niveles
            for ey in self.ejes_y
            for ex in self.ejes_x
        ]


def ejes_de_plano(c: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ejes (1, 2, 3) de un cuadrilátero de esquinas c (4, 3); ver `Edificio.ejes_area`."""
    n = np.cross(c[2] - c[0], c[3] - c[1])
    n /= np.linalg.norm(n)
    Z = np.array([0.0, 0.0, 1.0])
    if abs(n[2]) > 0.999:  # horizontal
        e3 = n if n[2] > 0 else -n
        e1 = np.array([1.0, 0.0, 0.0])
    else:
        e1 = np.cross(Z, n)
        e1 /= np.linalg.norm(e1)
        e3 = n
    e1 = e1 - np.dot(e1, e3) * e3
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e3, e1)
    return e1, e2, e3


def _revisar_cuadrilatero(c: np.ndarray, tol_alabeo: float = 1e-3) -> str | None:
    """Mensaje si el cuadrilátero no es plano, es degenerado o no es convexo; None si está bien."""
    n = np.cross(c[2] - c[0], c[3] - c[1])
    a = np.linalg.norm(n)
    if a < 1e-9:
        return "superficie nula o los nodos no siguen el perímetro"
    n /= a
    tam = max(np.linalg.norm(c[k] - c[k - 1]) for k in range(4))
    if np.abs((c - c.mean(axis=0)) @ n).max() > tol_alabeo * tam:
        return "los cuatro nodos no están en un plano"
    for k in range(4):
        giro = np.dot(np.cross(c[(k + 1) % 4] - c[k], c[(k + 2) % 4] - c[(k + 1) % 4]), n)
        if giro <= 1e-9 * tam**2:
            return "no es convexo o los nodos no siguen el perímetro"
    return None


def _letra(k: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA…"""
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


class Edificio(BaseModel):
    nombre: str
    materiales: list[Material] = []
    secciones: list[Seccion] = []
    secciones_area: list[SeccionArea] = []
    nodos: list[Nodo] = []
    barras: list[Barra] = []
    areas: list[Area] = []
    apoyos: list[Apoyo] = []
    patrones: list[PatronCarga] = []
    cargas_nodales: list[CargaNodal] = []
    cargas_distribuidas: list[CargaDistribuida] = []
    cargas_area: list[CargaArea] = []
    combinaciones: list[Combinacion] = []
    # Masa para análisis dinámico (ver modelo/masas.py)
    fuente_masa: dict[str, float] = Field(default_factory=dict, description="patrón -> factor")
    peso_propio_en_masa: bool = True
    masas_nodales: list[MasaNodal] = []
    espectro: Espectro | None = None
    # Espectro para la revisión de servicio (limitación de daños), elástico y para la intensidad
    # frecuente según las NTC 2023; opcional
    espectro_servicio: Espectro | None = None
    diafragmas: list[Diafragma] = []
    # Tamaño máximo de los elementos de cáscara en que se dividen muros y losas
    tamano_malla: float = Field(1.0, gt=0, description="m")
    # Solo para dibujar en la ventana; no entra en el análisis
    rejilla: Rejilla | None = None

    # --- búsquedas ---------------------------------------------------------
    def material(self, nombre: str) -> Material:
        return _buscar(self.materiales, "nombre", nombre, "material")

    def seccion(self, nombre: str) -> SeccionRectangular | SeccionGeneral:
        return _buscar(self.secciones, "nombre", nombre, "sección")

    def nodo(self, id_: str) -> Nodo:
        return _buscar(self.nodos, "id", id_, "nodo")

    def barra(self, id_: str) -> Barra:
        return _buscar(self.barras, "id", id_, "barra")

    def seccion_area(self, nombre: str) -> SeccionArea:
        return _buscar(self.secciones_area, "nombre", nombre, "sección de área")

    def area(self, id_: str) -> Area:
        return _buscar(self.areas, "id", id_, "área")

    # --- validación de referencias ----------------------------------------
    @model_validator(mode="after")
    def _validar_referencias(self) -> "Edificio":
        errores: list[str] = []
        for nombre, items, clave in [
            ("materiales", self.materiales, "nombre"),
            ("secciones", [*self.secciones, *self.secciones_area], "nombre"),
            ("nodos", self.nodos, "id"),
            ("barras", self.barras, "id"),
            ("áreas", self.areas, "id"),
            ("patrones", self.patrones, "nombre"),
            ("combinaciones", self.combinaciones, "nombre"),
            ("diafragmas", self.diafragmas, "nombre"),
        ]:
            vistos: set[str] = set()
            for it in items:
                k = getattr(it, clave)
                if k in vistos:
                    errores.append(f"{nombre}: '{k}' repetido")
                vistos.add(k)

        mats = {m.nombre for m in self.materiales}
        secs = {s.nombre for s in self.secciones}
        nods = {n.id for n in self.nodos}
        bars = {b.id for b in self.barras}
        pats = {p.nombre for p in self.patrones}

        for s in self.secciones:
            if s.material not in mats:
                errores.append(f"sección '{s.nombre}': material '{s.material}' no existe")
        secs_area = {s.nombre for s in self.secciones_area}
        ares = {a.id for a in self.areas}
        for s in self.secciones_area:
            if s.material not in mats:
                errores.append(f"sección '{s.nombre}': material '{s.material}' no existe")
        coords = {n.id: n.coords for n in self.nodos}
        for a in self.areas:
            faltan = [n for n in a.nodos if n not in nods]
            if faltan:
                errores.append(f"área '{a.id}': nodos {faltan} no existen")
            elif len(set(a.nodos)) < 4:
                errores.append(f"área '{a.id}': nodos repetidos")
            else:
                problema = _revisar_cuadrilatero(np.array([coords[n] for n in a.nodos]))
                if problema:
                    errores.append(f"área '{a.id}': {problema}")
            if a.seccion not in secs_area:
                errores.append(f"área '{a.id}': sección '{a.seccion}' no existe")
        for c in self.cargas_area:
            if c.area not in ares:
                errores.append(f"carga en área: área '{c.area}' no existe")
            if c.patron not in pats:
                errores.append(f"carga en área: patrón '{c.patron}' no existe")
        for b in self.barras:
            for n in (b.i, b.j):
                if n not in nods:
                    errores.append(f"barra '{b.id}': nodo '{n}' no existe")
            if b.i == b.j:
                errores.append(f"barra '{b.id}': nodo inicial y final iguales")
            if b.seccion not in secs:
                errores.append(f"barra '{b.id}': sección '{b.seccion}' no existe")
        for a in self.apoyos:
            if a.nodo not in nods:
                errores.append(f"apoyo: nodo '{a.nodo}' no existe")
        for c in self.cargas_nodales:
            if c.nodo not in nods:
                errores.append(f"carga nodal: nodo '{c.nodo}' no existe")
            if c.patron not in pats:
                errores.append(f"carga nodal: patrón '{c.patron}' no existe")
        for c in self.cargas_distribuidas:
            if c.barra not in bars:
                errores.append(f"carga distribuida: barra '{c.barra}' no existe")
            if c.patron not in pats:
                errores.append(f"carga distribuida: patrón '{c.patron}' no existe")
        for p in self.fuente_masa:
            if p not in pats:
                errores.append(f"fuente_masa: patrón '{p}' no existe")
        for mn in self.masas_nodales:
            if mn.nodo not in nods:
                errores.append(f"masa nodal: nodo '{mn.nodo}' no existe")
        for co in self.combinaciones:
            for p in co.factores:
                if p not in pats:
                    errores.append(f"combinación '{co.nombre}': patrón '{p}' no existe")

        cotas: list[float] = []
        for d in self.diafragmas:
            if any(math.isclose(d.z, z, abs_tol=1e-6) for z in cotas):
                errores.append(f"diafragma '{d.nombre}': ya hay otro diafragma a z = {d.z:g}")
            cotas.append(d.z)

        if errores:
            raise ValueError("Modelo inválido:\n- " + "\n- ".join(errores))
        return self

    # --- geometría ----------------------------------------------------------
    def ejes_locales(self, barra: Barra) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vectores unitarios (x, y, z) locales de una barra en ejes globales."""
        pi, pj = self.nodo(barra.i).coords, self.nodo(barra.j).coords
        d = pj - pi
        L = float(np.linalg.norm(d))
        if L == 0:
            raise ValueError(f"barra '{barra.id}' de longitud nula")
        x = d / L
        if math.isclose(d[0], 0.0, abs_tol=1e-9) and math.isclose(d[1], 0.0, abs_tol=1e-9):
            if d[2] > 0:
                y, z = np.array([-1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0])
            else:
                y, z = np.array([1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0])
        else:
            z = np.cross(x, [0.0, 0.0, 1.0])
            z /= np.linalg.norm(z)
            y = np.cross(z, x)
        if barra.rotacion:
            a = math.radians(barra.rotacion)
            y, z = math.cos(a) * y + math.sin(a) * z, -math.sin(a) * y + math.cos(a) * z
        return x, y, z

    def longitud(self, barra: Barra) -> float:
        return float(np.linalg.norm(self.nodo(barra.j).coords - self.nodo(barra.i).coords))

    def esquinas(self, area: Area) -> np.ndarray:
        """Coordenadas (4, 3) de las esquinas de un muro o losa."""
        return np.array([self.nodo(n).coords for n in area.nodos], dtype=float)

    def superficie(self, area: Area) -> float:
        """Área (m²) del cuadrilátero."""
        c = self.esquinas(area)
        return 0.5 * float(np.linalg.norm(np.cross(c[2] - c[0], c[3] - c[1])))

    def modulos_area(self, seccion: SeccionArea) -> tuple[float, float, float]:
        """(E, ν, G) de la cáscara de una sección de muro o losa, con sus modificadores.

        G es el módulo de cortante en el plano; en mampostería 0.2·Em (NTC Mampostería
        2.8.6.4.1), que un material isótropo no puede dar, así que los motores usan entonces un
        material ortótropo con ese G en el plano."""
        m = self.material(seccion.material)
        E = m.E * seccion.mod_rigidez
        return E, m.nu, m.G * seccion.mod_rigidez * seccion.mod_cortante

    def ejes_area(self, area: Area) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Ejes locales (1, 2, 3) de un muro o losa, en ejes globales.

        3 es normal al plano. En losas 3 apunta hacia arriba, 1 = X y 2 = Y (si son horizontales).
        En muros 1 es horizontal a lo largo del muro y 2 vertical hacia arriba.
        """
        return ejes_de_plano(self.esquinas(area))

    # --- archivos -----------------------------------------------------------
    @classmethod
    def cargar(cls, ruta: str) -> "Edificio":
        with open(ruta, encoding="utf-8") as f:
            return cls.model_validate_json(f.read())

    def guardar(self, ruta: str) -> None:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))


def _buscar(items, clave, valor, que):
    for it in items:
        if getattr(it, clave) == valor:
            return it
    raise KeyError(f"{que} '{valor}' no existe")
