"""Edición del modelo con deshacer y rehacer, sin dependencias de interfaz gráfica.

Cada operación trabaja sobre una copia del modelo, la valida completa con `Edificio` y,
solo si es válida, la vuelve el modelo actual y guarda el anterior en la historia.
Si la operación deja el modelo inválido, lanza `ValueError` y nada cambia.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Iterable, Literal

from pydantic import ValidationError

from .edificio import (
    Apoyo,
    Barra,
    CargaDistribuida,
    CargaNodal,
    Combinacion,
    Edificio,
    Material,
    Nodo,
    PatronCarga,
    Rejilla,
    SeccionRectangular,
)

TOLERANCIA = 1e-6  # m: dos nodos más cercanos que esto son el mismo punto

EMPOTRADO = (True, True, True, True, True, True)
ARTICULADO = (True, True, True, False, False, False)

Coleccion = Literal["materiales", "secciones", "patrones", "combinaciones"]
Punto = str | tuple[float, float, float]


def modelo_inicial(nombre: str, rejilla: Rejilla | None = None) -> Edificio:
    """Modelo vacío con un material, dos secciones, patrones y combinaciones de partida.

    Los valores son de arranque y se editan en Definir: concreto f'c = 250 kg/cm²
    (E ≈ 14 000·√f'c kg/cm² ≈ 22 GPa), combinaciones de gravedad 1.3CM + 1.5CV de las NTC.
    """
    return Edificio(
        nombre=nombre,
        materiales=[Material(nombre="Concreto f'c 250", tipo="concreto", E=22_000_000.0, nu=0.2, peso_vol=24.0)],
        secciones=[
            SeccionRectangular(nombre="C40x40", material="Concreto f'c 250", b=0.40, h=0.40),
            SeccionRectangular(nombre="V25x50", material="Concreto f'c 250", b=0.25, h=0.50),
        ],
        patrones=[PatronCarga(nombre="CM", tipo="muerta"), PatronCarga(nombre="CV", tipo="viva")],
        combinaciones=[
            Combinacion(nombre="CM+CV", factores={"CM": 1.0, "CV": 1.0}),
            Combinacion(nombre="1.3CM+1.5CV", factores={"CM": 1.3, "CV": 1.5}),
        ],
        fuente_masa={"CM": 1.0},
        rejilla=rejilla,
    )


class Editor:
    """Modelo actual más su historia. `observadores` se llaman después de cada cambio."""

    def __init__(self, modelo: Edificio | None = None, max_historia: int = 200):
        self.modelo = modelo
        self.max_historia = max_historia
        self._atras: list[tuple[str, Edificio]] = []
        self._adelante: list[tuple[str, Edificio]] = []
        self.modificado = False
        self.observadores: list[Callable[[], None]] = []

    # --- historia -------------------------------------------------------------
    def cargar(self, modelo: Edificio | None) -> None:
        """Reemplaza el modelo y borra la historia (al abrir o crear un archivo)."""
        self.modelo = modelo
        self._atras.clear()
        self._adelante.clear()
        self.modificado = False
        self._avisar()

    @property
    def puede_deshacer(self) -> bool:
        return bool(self._atras)

    @property
    def puede_rehacer(self) -> bool:
        return bool(self._adelante)

    @property
    def texto_deshacer(self) -> str:
        return self._atras[-1][0] if self._atras else ""

    @property
    def texto_rehacer(self) -> str:
        return self._adelante[-1][0] if self._adelante else ""

    def deshacer(self) -> str:
        if not self._atras:
            return ""
        desc, anterior = self._atras.pop()
        self._adelante.append((desc, self.modelo))
        self.modelo = anterior
        self.modificado = True
        self._avisar()
        return desc

    def rehacer(self) -> str:
        if not self._adelante:
            return ""
        desc, siguiente = self._adelante.pop()
        self._atras.append((desc, self.modelo))
        self.modelo = siguiente
        self.modificado = True
        self._avisar()
        return desc

    def _aplicar(self, descripcion: str, cambio: Callable[[Edificio], object]):
        """Aplica `cambio` a una copia; si la copia es válida, la vuelve el modelo actual."""
        if self.modelo is None:
            raise ValueError("no hay modelo abierto")
        copia = self.modelo.model_copy(deep=True)
        resultado = cambio(copia)
        # Revalida todo, incluidas las referencias entre objetos.
        try:
            nuevo = Edificio.model_validate(copia.model_dump())
        except ValidationError as e:
            raise ValueError(_mensaje(e)) from None
        self._atras.append((descripcion, self.modelo))
        del self._atras[: -self.max_historia]
        self._adelante.clear()
        self.modelo = nuevo
        self.modificado = True
        self._avisar()
        return resultado

    def _avisar(self) -> None:
        for f in self.observadores:
            f()

    # --- modelo y rejilla -------------------------------------------------------
    def nuevo(self, nombre: str, rejilla: Rejilla | None = None) -> None:
        self.cargar(modelo_inicial(nombre, rejilla))
        self.modificado = True

    def definir_rejilla(self, rejilla: Rejilla | None) -> None:
        def cambio(m: Edificio) -> None:
            m.rejilla = rejilla

        self._aplicar("Editar rejilla", cambio)

    def renombrar_modelo(self, nombre: str) -> None:
        def cambio(m: Edificio) -> None:
            m.nombre = nombre

        self._aplicar("Renombrar modelo", cambio)

    # --- nodos y barras ---------------------------------------------------------
    def agregar_nodo(self, x: float, y: float, z: float, id_: str | None = None) -> str:
        """Agrega un nodo (o devuelve el que ya existe en ese punto)."""
        return self._aplicar("Agregar nodo", lambda m: _nodo_en(m, (x, y, z), id_))

    def agregar_barra(self, i: Punto, j: Punto, seccion: str, tipo: str | None = None) -> str:
        """Barra entre dos nodos (id) o puntos (x, y, z); los puntos sin nodo crean uno.
        Sin `tipo`, se deduce: vertical = columna, horizontal = viga, inclinada = contraviento."""
        return self._aplicar("Agregar barra", lambda m: _barra_entre(m, i, j, seccion, tipo))

    def agregar_columnas(self, puntos: Iterable[tuple[float, float]], nivel_inf: float, nivel_sup: float, seccion: str) -> list[str]:
        """Una columna por punto (x, y) entre dos elevaciones."""

        def cambio(m: Edificio) -> list[str]:
            return [_barra_entre(m, (x, y, nivel_inf), (x, y, nivel_sup), seccion, "columna") for x, y in puntos]

        return self._aplicar("Agregar columnas", cambio)

    def marco_desde_rejilla(
        self,
        seccion_columna: str,
        seccion_viga: str,
        niveles: Iterable[str] | None = None,
        apoyos_en_base: bool = True,
    ) -> int:
        """Columnas en cada cruce de ejes y vigas sobre cada eje, en los niveles indicados
        (todos menos la base si no se indican). Omite lo que ya existe. Devuelve cuántas barras creó."""

        def cambio(m: Edificio) -> int:
            r = m.rejilla
            if r is None or len(r.niveles) < 2 or not r.ejes_x or not r.ejes_y:
                raise ValueError("la rejilla necesita ejes X, ejes Y y al menos dos niveles")
            elegidos = set(niveles) if niveles is not None else {n.nombre for n in r.niveles[1:]}
            antes = len(m.barras)
            for k in range(1, len(r.niveles)):
                nv, abajo = r.niveles[k], r.niveles[k - 1]
                if nv.nombre not in elegidos:
                    continue
                for ey in r.ejes_y:
                    for ex in r.ejes_x:
                        _barra_entre(m, (ex.coord, ey.coord, abajo.z), (ex.coord, ey.coord, nv.z), seccion_columna, "columna")
                for ey in r.ejes_y:
                    for a, b in zip(r.ejes_x, r.ejes_x[1:]):
                        _barra_entre(m, (a.coord, ey.coord, nv.z), (b.coord, ey.coord, nv.z), seccion_viga, "viga")
                for ex in r.ejes_x:
                    for a, b in zip(r.ejes_y, r.ejes_y[1:]):
                        _barra_entre(m, (ex.coord, a.coord, nv.z), (ex.coord, b.coord, nv.z), seccion_viga, "viga")
            if apoyos_en_base:
                z0 = r.niveles[0].z
                base = [n.id for n in m.nodos if math.isclose(n.z, z0, abs_tol=TOLERANCIA)]
                _asignar_apoyo(m, base, EMPOTRADO, solo_nuevos=True)
            return len(m.barras) - antes

        return self._aplicar("Marco desde rejilla", cambio)

    def borrar(self, nodos: Iterable[str] = (), barras: Iterable[str] = ()) -> None:
        """Borra nodos y barras. Un nodo se lleva sus barras, apoyo, cargas y masas;
        una barra, sus cargas distribuidas."""
        nodos, barras = set(nodos), set(barras)
        if not nodos and not barras:
            return

        def cambio(m: Edificio) -> None:
            quitar_b = barras | {b.id for b in m.barras if b.i in nodos or b.j in nodos}
            m.nodos = [n for n in m.nodos if n.id not in nodos]
            m.barras = [b for b in m.barras if b.id not in quitar_b]
            m.apoyos = [a for a in m.apoyos if a.nodo not in nodos]
            m.cargas_nodales = [c for c in m.cargas_nodales if c.nodo not in nodos]
            m.masas_nodales = [c for c in m.masas_nodales if c.nodo not in nodos]
            m.cargas_distribuidas = [c for c in m.cargas_distribuidas if c.barra not in quitar_b]

        n = len(nodos) + len(barras)
        self._aplicar(f"Borrar {n} objeto{'s' if n != 1 else ''}", cambio)

    def editar_nodo(self, id_: str, *, id_nuevo: str | None = None, x: float | None = None, y: float | None = None, z: float | None = None) -> None:
        def cambio(m: Edificio) -> None:
            n = m.nodo(id_)
            for campo, valor in (("x", x), ("y", y), ("z", z)):
                if valor is not None:
                    setattr(n, campo, float(valor))
            if id_nuevo and id_nuevo != id_:
                _exigir_libre(id_nuevo, (o.id for o in m.nodos), "nodo")
                n.id = id_nuevo
                for b in m.barras:
                    b.i = id_nuevo if b.i == id_ else b.i
                    b.j = id_nuevo if b.j == id_ else b.j
                for lst in (m.apoyos, m.cargas_nodales, m.masas_nodales):
                    for o in lst:
                        if o.nodo == id_:
                            o.nodo = id_nuevo
            otro = _nodo_existente(m, (n.x, n.y, n.z), excepto=n.id)
            if otro:
                raise ValueError(f"ya hay un nodo ({otro}) en ese punto")

        self._aplicar(f"Editar nodo {id_}", cambio)

    def editar_barra(self, id_: str, **cambios) -> None:
        """Cambia campos de una barra: id (renombra), tipo, i, j, seccion, rotacion."""

        def cambio(m: Edificio) -> None:
            b = m.barra(id_)
            id_nuevo = cambios.pop("id", None)
            datos = b.model_dump() | cambios
            nueva = Barra.model_validate(datos)
            for campo in Barra.model_fields:
                setattr(b, campo, getattr(nueva, campo))
            if id_nuevo and id_nuevo != id_:
                _exigir_libre(id_nuevo, (o.id for o in m.barras), "barra")
                b.id = id_nuevo
                for c in m.cargas_distribuidas:
                    if c.barra == id_:
                        c.barra = id_nuevo

        self._aplicar(f"Editar barra {id_}", cambio)

    # --- asignaciones ---------------------------------------------------------
    def asignar_apoyo(self, nodos: Iterable[str], restricciones: tuple[bool, ...] | None) -> None:
        """`restricciones` = (UX, UY, UZ, RX, RY, RZ); None o todo libre quita el apoyo."""
        nodos = list(nodos)
        self._aplicar("Asignar apoyos", lambda m: _asignar_apoyo(m, nodos, restricciones))

    def asignar_seccion(self, barras: Iterable[str], seccion: str) -> None:
        barras = set(barras)

        def cambio(m: Edificio) -> None:
            for b in m.barras:
                if b.id in barras:
                    b.seccion = seccion

        self._aplicar(f"Asignar sección {seccion}", cambio)

    def asignar_carga_nodal(self, nodos: Iterable[str], patron: str, fuerzas: tuple[float, ...], reemplazar: bool = True) -> None:
        """Fuerzas (FX, FY, FZ, MX, MY, MZ) en el patrón. Con `reemplazar`, quita antes las
        cargas de ese patrón en esos nodos; con fuerzas nulas, solo las quita."""
        nodos = list(nodos)
        fuerzas = tuple(float(f) for f in fuerzas)

        def cambio(m: Edificio) -> None:
            if reemplazar:
                m.cargas_nodales = [c for c in m.cargas_nodales if not (c.patron == patron and c.nodo in nodos)]
            if any(fuerzas):
                m.cargas_nodales += [CargaNodal(patron=patron, nodo=n, fuerzas=fuerzas) for n in nodos]

        self._aplicar(f"Asignar carga nodal {patron}", cambio)

    def asignar_carga_distribuida(self, barras: Iterable[str], patron: str, direccion: str, w: float, reemplazar: bool = True) -> None:
        """Carga uniforme en dirección global; con `reemplazar`, quita antes las de ese patrón y
        dirección en esas barras. w = 0 solo las quita."""
        barras = list(barras)

        def cambio(m: Edificio) -> None:
            if reemplazar:
                m.cargas_distribuidas = [
                    c for c in m.cargas_distribuidas
                    if not (c.patron == patron and c.direccion == direccion and c.barra in barras)
                ]
            if w:
                m.cargas_distribuidas += [CargaDistribuida(patron=patron, barra=b, direccion=direccion, w=float(w)) for b in barras]

        self._aplicar(f"Asignar carga distribuida {patron}", cambio)

    # --- definiciones ---------------------------------------------------------
    def reemplazar(self, coleccion: Coleccion, items: list, renombres: dict[str, str] | None = None) -> None:
        """Reemplaza la lista completa de materiales, secciones, patrones o combinaciones
        (lo que entrega una tabla de Definir). `renombres` (anterior -> nuevo) se propaga a
        todo lo que hace referencia al nombre, como haría ETABS."""
        renombres = {a: b for a, b in (renombres or {}).items() if a != b}

        def cambio(m: Edificio) -> None:
            setattr(m, coleccion, list(items))
            r = renombres.get
            if coleccion == "materiales":
                for s in m.secciones:
                    s.material = r(s.material, s.material)
            elif coleccion == "secciones":
                for b in m.barras:
                    b.seccion = r(b.seccion, b.seccion)
            elif coleccion == "patrones":
                for c in (*m.cargas_nodales, *m.cargas_distribuidas):
                    c.patron = r(c.patron, c.patron)
                for co in m.combinaciones:
                    co.factores = {r(p, p): f for p, f in co.factores.items()}
                m.fuente_masa = {r(p, p): f for p, f in m.fuente_masa.items()}

        nombres = {"materiales": "materiales", "secciones": "secciones", "patrones": "patrones de carga", "combinaciones": "combinaciones"}
        self._aplicar(f"Editar {nombres[coleccion]}", cambio)

    def definir_masa(self, fuente: dict[str, float], peso_propio: bool) -> None:
        def cambio(m: Edificio) -> None:
            m.fuente_masa = dict(fuente)
            m.peso_propio_en_masa = peso_propio

        self._aplicar("Editar fuente de masa", cambio)

    def definir_espectro(self, espectro) -> None:
        def cambio(m: Edificio) -> None:
            m.espectro = espectro

        self._aplicar("Editar espectro", cambio)


def _mensaje(e: ValidationError) -> str:
    """Texto legible de un error de validación de pydantic."""
    partes = []
    for err in e.errors():
        msg = err["msg"].removeprefix("Value error, ")
        donde = ".".join(str(x) for x in err["loc"])
        partes.append(f"{donde}: {msg}" if donde else msg)
    return "\n".join(partes)


# --- utilidades sobre una copia del modelo ------------------------------------------
def _nodo_existente(m: Edificio, p: tuple[float, float, float], excepto: str | None = None) -> str | None:
    for n in m.nodos:
        if n.id != excepto and all(math.isclose(a, b, abs_tol=TOLERANCIA) for a, b in zip((n.x, n.y, n.z), p)):
            return n.id
    return None


def _nombre_en_rejilla(m: Edificio, p: tuple[float, float, float]) -> str | None:
    r = m.rejilla
    if r is None:
        return None
    for nombre, q in r.intersecciones():
        if all(math.isclose(a, b, abs_tol=TOLERANCIA) for a, b in zip(p, q)):
            return nombre
    return None


def _siguiente(prefijo: str, usados: Iterable[str]) -> str:
    patron = re.compile(re.escape(prefijo) + r"(\d+)$")
    k = max((int(g.group(1)) for u in usados if (g := patron.match(u))), default=0)
    return f"{prefijo}{k + 1}"


def _exigir_libre(id_: str, usados: Iterable[str], que: str) -> None:
    if id_ in set(usados):
        raise ValueError(f"ya existe un {que} llamado '{id_}'")


def _nodo_en(m: Edificio, p: tuple[float, float, float], id_: str | None = None) -> str:
    p = tuple(float(v) for v in p)
    existente = _nodo_existente(m, p)
    if existente:
        return existente
    usados = {n.id for n in m.nodos}
    if id_:
        _exigir_libre(id_, usados, "nodo")
    else:
        id_ = _nombre_en_rejilla(m, p)
        if id_ is None or id_ in usados:
            id_ = _siguiente("N", usados)
    m.nodos.append(Nodo(id=id_, x=p[0], y=p[1], z=p[2]))
    return id_


_PREFIJOS = {"columna": "C", "viga": "V", "contraviento": "D", "barra": "B"}


def _barra_entre(m: Edificio, i: Punto, j: Punto, seccion: str, tipo: str | None) -> str:
    ni = i if isinstance(i, str) else _nodo_en(m, i)
    nj = j if isinstance(j, str) else _nodo_en(m, j)
    if ni == nj:
        raise ValueError("los dos extremos de la barra son el mismo nodo")
    for b in m.barras:
        if {b.i, b.j} == {ni, nj}:
            return b.id  # ya existe: no se duplica
    a, c = m.nodo(ni), m.nodo(nj)
    if tipo is None:
        horizontal = math.isclose(a.z, c.z, abs_tol=TOLERANCIA)
        vertical = math.isclose(a.x, c.x, abs_tol=TOLERANCIA) and math.isclose(a.y, c.y, abs_tol=TOLERANCIA)
        tipo = "columna" if vertical else "viga" if horizontal else "contraviento"
    if tipo == "columna" and a.z > c.z:
        ni, nj = nj, ni  # las columnas van de abajo hacia arriba
    id_ = _siguiente(_PREFIJOS.get(tipo, "B"), (b.id for b in m.barras))
    m.barras.append(Barra(id=id_, tipo=tipo, i=ni, j=nj, seccion=seccion))
    return id_


def _asignar_apoyo(m: Edificio, nodos: list[str], restricciones, solo_nuevos: bool = False) -> None:
    nodos = set(nodos)
    existentes = {a.nodo for a in m.apoyos}
    if solo_nuevos:
        nodos -= existentes
    else:
        m.apoyos = [a for a in m.apoyos if a.nodo not in nodos]
    if restricciones is None or not any(restricciones):
        return
    for n in m.nodos:  # en el orden de los nodos, para un JSON estable
        if n.id in nodos:
            m.apoyos.append(Apoyo(nodo=n.id, restricciones=tuple(bool(r) for r in restricciones)))
