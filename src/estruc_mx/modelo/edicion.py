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
    Area,
    Barra,
    CargaArea,
    CargaDistribuida,
    CargaNodal,
    Combinacion,
    Diafragma,
    Edificio,
    MasaNodal,
    Material,
    Nodo,
    PatronCarga,
    Rejilla,
    SeccionArea,
    SeccionRectangular,
)

TOLERANCIA = 1e-6  # m: dos nodos más cercanos que esto son el mismo punto

EMPOTRADO = (True, True, True, True, True, True)
ARTICULADO = (True, True, True, False, False, False)

Coleccion = Literal["materiales", "secciones", "secciones_area", "patrones", "combinaciones"]
Punto = str | tuple[float, float, float]


def modelo_inicial(nombre: str, rejilla: Rejilla | None = None) -> Edificio:
    """Modelo vacío con un material, dos secciones, patrones y combinaciones de partida.

    Los valores son de arranque y se editan en Definir: concreto f'c = 250 kg/cm²
    (E ≈ 14 000·√f'c kg/cm² ≈ 22 GPa), combinaciones de gravedad 1.3CM + 1.5CV de las NTC.
    Mampostería de tabique rojo recocido con f'm ≈ 15 kg/cm² y Em = 600·f'm ≈ 0.88 GPa
    (NTC Mampostería, cargas de corta duración).
    """
    return Edificio(
        nombre=nombre,
        materiales=[
            Material(nombre="Concreto f'c 250", tipo="concreto", E=22_000_000.0, nu=0.2, peso_vol=24.0),
            Material(nombre="Tabique rojo", tipo="mamposteria", E=880_000.0, nu=0.25, peso_vol=15.0),
        ],
        secciones=[
            SeccionRectangular(nombre="C40x40", material="Concreto f'c 250", b=0.40, h=0.40),
            SeccionRectangular(nombre="V25x50", material="Concreto f'c 250", b=0.25, h=0.50),
        ],
        secciones_area=[
            SeccionArea(nombre="Muro concreto 15", material="Concreto f'c 250", tipo="muro", espesor=0.15),
            SeccionArea(nombre="Muro tabique 14", material="Tabique rojo", tipo="muro", espesor=0.14),
            SeccionArea(nombre="Losa 10", material="Concreto f'c 250", tipo="losa", espesor=0.10),
        ],
        # CM incluye el peso propio de barras, muros y losas; la masa lo cuenta una sola vez
        patrones=[PatronCarga(nombre="CM", tipo="muerta", peso_propio=1.0), PatronCarga(nombre="CV", tipo="viva")],
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

    def borrar(self, nodos: Iterable[str] = (), barras: Iterable[str] = (), areas: Iterable[str] = ()) -> None:
        """Borra nodos, barras y áreas. Un nodo se lleva sus barras, áreas, apoyo, cargas y masas;
        una barra o un área, sus cargas."""
        nodos, barras, areas = set(nodos), set(barras), set(areas)
        if not nodos and not barras and not areas:
            return

        def cambio(m: Edificio) -> None:
            quitar_b = barras | {b.id for b in m.barras if b.i in nodos or b.j in nodos}
            quitar_a = areas | {a.id for a in m.areas if set(a.nodos) & nodos}
            m.nodos = [n for n in m.nodos if n.id not in nodos]
            m.barras = [b for b in m.barras if b.id not in quitar_b]
            m.areas = [a for a in m.areas if a.id not in quitar_a]
            m.apoyos = [a for a in m.apoyos if a.nodo not in nodos]
            m.cargas_nodales = [c for c in m.cargas_nodales if c.nodo not in nodos]
            m.masas_nodales = [c for c in m.masas_nodales if c.nodo not in nodos]
            m.cargas_distribuidas = [c for c in m.cargas_distribuidas if c.barra not in quitar_b]
            m.cargas_area = [c for c in m.cargas_area if c.area not in quitar_a]

        n = len(nodos) + len(barras) + len(areas)
        self._aplicar(f"Borrar {n} objeto{'s' if n != 1 else ''}", cambio)

    # --- muros y losas ----------------------------------------------------------
    def agregar_area(self, puntos: Iterable[Punto], seccion: str, tipo: str | None = None) -> str:
        """Muro o losa con cuatro esquinas (ids de nodo o puntos) en orden alrededor del perímetro.
        Sin `tipo`, se deduce: horizontal = losa, si no, muro."""
        puntos = list(puntos)
        return self._aplicar("Agregar área", lambda m: _area_en(m, puntos, seccion, tipo))

    def agregar_muro(self, p1: tuple[float, float], p2: tuple[float, float], z_inf: float, z_sup: float, seccion: str) -> str:
        """Muro vertical entre dos puntos (x, y) en planta, de la elevación z_inf a la z_sup."""
        if z_sup <= z_inf + TOLERANCIA:
            raise ValueError("el muro necesita z_sup mayor que z_inf")
        (x1, y1), (x2, y2) = p1, p2
        esquinas = [(x1, y1, z_inf), (x2, y2, z_inf), (x2, y2, z_sup), (x1, y1, z_sup)]

        def cambio(m: Edificio) -> str:
            id_ = _area_en(m, esquinas, seccion, "muro")
            # Un muro que arranca en la base de la rejilla queda empotrado, como el marco
            if m.rejilla is not None and m.rejilla.niveles and math.isclose(z_inf, m.rejilla.niveles[0].z, abs_tol=TOLERANCIA):
                _asignar_apoyo(m, list(m.area(id_).nodos[:2]), EMPOTRADO, solo_nuevos=True)
            return id_

        return self._aplicar("Agregar muro", cambio)

    def agregar_losa(self, p1: tuple[float, float], p2: tuple[float, float], z: float, seccion: str) -> str:
        """Losa rectangular con esquinas opuestas p1 y p2 (x, y) a la elevación z."""
        (x1, y1), (x2, y2) = p1, p2
        if abs(x2 - x1) < TOLERANCIA or abs(y2 - y1) < TOLERANCIA:
            raise ValueError("las esquinas de la losa deben ser opuestas (distinta X y distinta Y)")
        xa, xb, ya, yb = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
        esquinas = [(xa, ya, z), (xb, ya, z), (xb, yb, z), (xa, yb, z)]
        return self._aplicar("Agregar losa", lambda m: _area_en(m, esquinas, seccion, "losa"))

    def losas_desde_rejilla(self, seccion: str, niveles: Iterable[str] | None = None) -> int:
        """Una losa en cada tablero de la rejilla en los niveles indicados (todos menos la base si
        no se indican). Omite las que ya existen. Devuelve cuántas creó."""

        def cambio(m: Edificio) -> int:
            r = m.rejilla
            if r is None or len(r.niveles) < 2 or len(r.ejes_x) < 2 or len(r.ejes_y) < 2:
                raise ValueError("la rejilla necesita al menos dos ejes en X, dos en Y y dos niveles")
            elegidos = set(niveles) if niveles is not None else {n.nombre for n in r.niveles[1:]}
            antes = len(m.areas)
            for nv in r.niveles:
                if nv.nombre not in elegidos:
                    continue
                for a, b in zip(r.ejes_x, r.ejes_x[1:]):
                    for c, d in zip(r.ejes_y, r.ejes_y[1:]):
                        esquinas = [(a.coord, c.coord, nv.z), (b.coord, c.coord, nv.z), (b.coord, d.coord, nv.z), (a.coord, d.coord, nv.z)]
                        _area_en(m, esquinas, seccion, "losa")
            return len(m.areas) - antes

        return self._aplicar("Losas desde rejilla", cambio)

    def asignar_seccion_area(self, areas: Iterable[str], seccion: str) -> None:
        areas = set(areas)

        def cambio(m: Edificio) -> None:
            for a in m.areas:
                if a.id in areas:
                    a.seccion = seccion

        self._aplicar(f"Asignar sección {seccion}", cambio)

    def asignar_carga_area(self, areas: Iterable[str], patron: str, direccion: str, w: float, reemplazar: bool = True) -> None:
        """Carga uniforme por m² en dirección global; con `reemplazar`, quita antes las de ese
        patrón y dirección en esas áreas. w = 0 solo las quita."""
        areas = list(areas)

        def cambio(m: Edificio) -> None:
            if reemplazar:
                m.cargas_area = [
                    c for c in m.cargas_area
                    if not (c.patron == patron and c.direccion == direccion and c.area in areas)
                ]
            if w:
                m.cargas_area += [CargaArea(patron=patron, area=a, direccion=direccion, w=float(w)) for a in areas]

        self._aplicar(f"Asignar carga en áreas {patron}", cambio)

    def editar_area(self, id_: str, **cambios) -> None:
        """Cambia campos de un área: id (renombra), tipo, seccion."""

        def cambio(m: Edificio) -> None:
            a = m.area(id_)
            id_nuevo = cambios.pop("id", None)
            nueva = Area.model_validate(a.model_dump() | cambios)
            for campo in Area.model_fields:
                setattr(a, campo, getattr(nueva, campo))
            if id_nuevo and id_nuevo != id_:
                _exigir_libre(id_nuevo, (o.id for o in m.areas), "área")
                a.id = id_nuevo
                for c in m.cargas_area:
                    if c.area == id_:
                        c.area = id_nuevo

        self._aplicar(f"Editar área {id_}", cambio)

    def definir_malla(self, tamano: float) -> None:
        def cambio(m: Edificio) -> None:
            m.tamano_malla = float(tamano)

        self._aplicar("Editar tamaño de malla", cambio)

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
                for a in m.areas:
                    a.nodos = tuple(id_nuevo if n == id_ else n for n in a.nodos)
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

    def editar_muro(self, id_: str, p1: tuple[float, float], p2: tuple[float, float], z_inf: float, z_sup: float) -> None:
        """Mueve un muro vertical: nuevos extremos en planta (x, y) y elevaciones de la base y la
        corona. Conserva id, sección y cargas; los nodos que quedan sin uso se borran."""
        if z_sup <= z_inf + TOLERANCIA:
            raise ValueError("el muro necesita z_sup mayor que z_inf")
        (x1, y1), (x2, y2) = p1, p2
        esquinas = [(x1, y1, z_inf), (x2, y2, z_inf), (x2, y2, z_sup), (x1, y1, z_sup)]

        def cambio(m: Edificio) -> None:
            a = m.area(id_)
            if a.tipo != "muro":
                raise ValueError(f"'{id_}' es una losa, no un muro")
            anteriores = set(a.nodos)
            nuevos = tuple(_nodo_en(m, p) for p in esquinas)
            if len(set(nuevos)) != 4:
                raise ValueError("las cuatro esquinas deben ser nodos distintos")
            for otra in m.areas:
                if otra.id != id_ and set(otra.nodos) == set(nuevos):
                    raise ValueError(f"ya hay un área ({otra.id}) en ese lugar")
            a.nodos = nuevos
            _borrar_nodos_sueltos(m, anteriores - set(nuevos))
            if m.rejilla is not None and m.rejilla.niveles and math.isclose(z_inf, m.rejilla.niveles[0].z, abs_tol=TOLERANCIA):
                _asignar_apoyo(m, list(nuevos[:2]), EMPOTRADO, solo_nuevos=True)

        self._aplicar(f"Editar muro {id_}", cambio)

    def dividir_area(self, id_: str, partes_1: int = 2, partes_2: int = 1) -> list[str]:
        """Divide un muro o losa en partes_1 × partes_2 áreas (1: de la esquina 0 a la 1, a lo
        largo del muro; 2: de la 0 a la 3, a lo alto). Las piezas conservan sección y cargas;
        la primera conserva el id. Útil para abrir huecos o unir el área con nodos intermedios."""
        if partes_1 < 1 or partes_2 < 1 or partes_1 * partes_2 < 2:
            raise ValueError("indica al menos dos partes")

        def cambio(m: Edificio) -> list[str]:
            a = m.area(id_)
            c = m.esquinas(a)
            cargas = [ca for ca in m.cargas_area if ca.area == id_]
            m.areas.remove(a)
            m.cargas_area = [ca for ca in m.cargas_area if ca.area != id_]
            existentes = {n.id for n in m.nodos}
            ids: list[str] = []

            def p(s: float, t: float) -> tuple[float, float, float]:
                q = (1 - s) * (1 - t) * c[0] + s * (1 - t) * c[1] + s * t * c[2] + (1 - s) * t * c[3]
                return tuple(float(v) for v in q)

            for j in range(partes_2):
                for i in range(partes_1):
                    s0, s1, t0, t1 = i / partes_1, (i + 1) / partes_1, j / partes_2, (j + 1) / partes_2
                    nodos = tuple(_nodo_en(m, q) for q in (p(s0, t0), p(s1, t0), p(s1, t1), p(s0, t1)))
                    nid = id_ if not ids else _siguiente("L" if a.tipo == "losa" else "M", [o.id for o in m.areas] + [id_])
                    m.areas.append(Area(id=nid, tipo=a.tipo, nodos=nodos, seccion=a.seccion))
                    m.cargas_area += [ca.model_copy(update={"area": nid}) for ca in cargas]
                    ids.append(nid)
            # Los nodos nuevos sobre un borde entre dos apoyos iguales heredan el apoyo (la base de un
            # muro empotrado sigue empotrada). Las barras sobre los bordes las parte la malla.
            apoyos = {ap.nodo: ap.restricciones for ap in m.apoyos}
            for k in range(4):
                ra, rb = apoyos.get(a.nodos[k]), apoyos.get(a.nodos[(k + 1) % 4])
                if ra is None or ra != rb:
                    continue
                p0, p1 = c[k], c[(k + 1) % 4]
                sobre = [
                    n.id for n in m.nodos
                    if n.id not in existentes and _sobre_segmento(n.coords, p0, p1)
                ]
                _asignar_apoyo(m, sobre, ra, solo_nuevos=True)
            return ids

        return self._aplicar(f"Dividir {id_}", cambio)

    # --- replicar -----------------------------------------------------------------
    def replicar(
        self,
        desplazamientos: Iterable[tuple[float, float, float]],
        nodos: Iterable[str] = (),
        barras: Iterable[str] = (),
        areas: Iterable[str] = (),
        con_cargas: bool = True,
    ) -> dict[str, int]:
        """Copia nodos, barras, muros y losas desplazados por cada vector (dx, dy, dz), como
        «Replicar» de ETABS. Las copias se unen con lo que ya existe en el mismo lugar y no se
        duplica nada. Con `con_cargas`, cada copia nueva lleva las cargas del original; los nodos
        nuevos llevan además su apoyo y su masa. Devuelve cuántos objetos nuevos creó."""
        desplazamientos = [tuple(float(v) for v in d) for d in desplazamientos]
        nodos, barras, areas = list(nodos), list(barras), list(areas)
        if not desplazamientos:
            raise ValueError("no hay a dónde replicar")
        if all(math.isclose(v, 0.0, abs_tol=TOLERANCIA) for d in desplazamientos for v in d):
            raise ValueError("el desplazamiento no puede ser cero")
        if not (nodos or barras or areas):
            raise ValueError("selecciona qué replicar")

        def cambio(m: Edificio) -> dict[str, int]:
            antes = (len(m.nodos), len(m.barras), len(m.areas))
            fuente_b = [m.barra(b) for b in barras]
            fuente_a = [m.area(a) for a in areas]
            todos = list(dict.fromkeys([*nodos, *(n for b in fuente_b for n in (b.i, b.j)), *(n for a in fuente_a for n in a.nodos)]))
            coords = {n: m.nodo(n).coords for n in todos}
            apoyos = {a.nodo: a for a in m.apoyos}
            c_nod = [c for c in m.cargas_nodales if c.nodo in coords]
            c_dist = [c for c in m.cargas_distribuidas if c.barra in set(barras)]
            c_area = [c for c in m.cargas_area if c.area in set(areas)]
            masas = [mn for mn in m.masas_nodales if mn.nodo in coords]
            for d in desplazamientos:
                existentes = {n.id for n in m.nodos}
                mapa = {n: _nodo_en(m, tuple(coords[n] + d)) for n in todos}
                nuevos_n = {n for n, k in mapa.items() if k not in existentes}
                if con_cargas:
                    for n in nuevos_n:
                        if n in apoyos:
                            m.apoyos.append(Apoyo(nodo=mapa[n], restricciones=apoyos[n].restricciones))
                    m.cargas_nodales += [c.model_copy(update={"nodo": mapa[c.nodo]}) for c in c_nod if c.nodo in nuevos_n]
                    m.masas_nodales += [MasaNodal(nodo=mapa[mn.nodo], masa=mn.masa) for mn in masas if mn.nodo in nuevos_n]
                for b in fuente_b:
                    previas = {o.id for o in m.barras}
                    nid = _barra_entre(m, mapa[b.i], mapa[b.j], b.seccion, b.tipo)
                    if nid in previas:
                        continue
                    m.barra(nid).rotacion = b.rotacion
                    if con_cargas:
                        m.cargas_distribuidas += [c.model_copy(update={"barra": nid}) for c in c_dist if c.barra == b.id]
                for a in fuente_a:
                    previas = {o.id for o in m.areas}
                    nid = _area_en(m, [mapa[n] for n in a.nodos], a.seccion, a.tipo)
                    if nid in previas:
                        continue
                    if con_cargas:
                        m.cargas_area += [c.model_copy(update={"area": nid}) for c in c_area if c.area == a.id]
            return {"nodos": len(m.nodos) - antes[0], "barras": len(m.barras) - antes[1], "areas": len(m.areas) - antes[2]}

        return self._aplicar("Replicar", cambio)

    def replicar_a_niveles(
        self, nivel_origen: str, niveles: Iterable[str], nodos: Iterable[str] = (), barras: Iterable[str] = (),
        areas: Iterable[str] = (), con_cargas: bool = True,
    ) -> dict[str, int]:
        """Replica lo indicado desde un nivel de la rejilla a otros niveles (solo cambia Z)."""
        r = self.modelo.rejilla if self.modelo is not None else None
        if r is None or not r.niveles:
            raise ValueError("hace falta una rejilla con niveles")
        cotas = {nv.nombre: nv.z for nv in r.niveles}
        faltan = [n for n in [nivel_origen, *niveles] if n not in cotas]
        if faltan:
            raise ValueError(f"niveles {faltan} no existen en la rejilla")
        dz = [(0.0, 0.0, cotas[n] - cotas[nivel_origen]) for n in niveles if n != nivel_origen]
        return self.replicar(dz, nodos, barras, areas, con_cargas)

    # --- diafragmas -----------------------------------------------------------------
    def asignar_diafragmas(self, niveles: Iterable[str | float], solo_estos: bool = False) -> None:
        """Diafragma rígido en cada nivel (nombre de nivel de la rejilla o elevación); reemplaza
        los que hubiera a esa altura. Se nombran como el nivel (o «D<z>»). Con `solo_estos`,
        quita antes todos los demás."""
        niveles = list(niveles)

        def cambio(m: Edificio) -> None:
            if solo_estos:
                m.diafragmas = []
            cotas = {nv.nombre: nv.z for nv in m.rejilla.niveles} if m.rejilla else {}
            for nv in niveles:
                if isinstance(nv, str):
                    if nv not in cotas:
                        raise ValueError(f"el nivel '{nv}' no existe en la rejilla")
                    nombre, z = nv, cotas[nv]
                else:
                    z = float(nv)
                    nombre = next((k for k, v in cotas.items() if math.isclose(v, z, abs_tol=TOLERANCIA)), f"D{z:g}")
                m.diafragmas = [d for d in m.diafragmas if not math.isclose(d.z, z, abs_tol=TOLERANCIA) and d.nombre != nombre]
                m.diafragmas.append(Diafragma(nombre=nombre, z=z))
            m.diafragmas.sort(key=lambda d: d.z)

        self._aplicar("Asignar diafragmas", cambio)

    def quitar_diafragmas(self, nombres: Iterable[str] | None = None) -> None:
        """Quita los diafragmas indicados (todos si no se indica ninguno)."""
        nombres = None if nombres is None else set(nombres)

        def cambio(m: Edificio) -> None:
            m.diafragmas = [] if nombres is None else [d for d in m.diafragmas if d.nombre not in nombres]

        self._aplicar("Quitar diafragmas", cambio)

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
                for s in (*m.secciones, *m.secciones_area):
                    s.material = r(s.material, s.material)
            elif coleccion == "secciones":
                for b in m.barras:
                    b.seccion = r(b.seccion, b.seccion)
            elif coleccion == "secciones_area":
                for a in m.areas:
                    a.seccion = r(a.seccion, a.seccion)
            elif coleccion == "patrones":
                for c in (*m.cargas_nodales, *m.cargas_distribuidas, *m.cargas_area):
                    c.patron = r(c.patron, c.patron)
                for co in m.combinaciones:
                    co.factores = {r(p, p): f for p, f in co.factores.items()}
                m.fuente_masa = {r(p, p): f for p, f in m.fuente_masa.items()}

        nombres = {
            "materiales": "materiales", "secciones": "secciones", "secciones_area": "secciones de muro y losa",
            "patrones": "patrones de carga", "combinaciones": "combinaciones",
        }
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


def _area_en(m: Edificio, puntos: list[Punto], seccion: str, tipo: str | None) -> str:
    if len(puntos) != 4:
        raise ValueError("un muro o losa necesita cuatro esquinas")
    ids = [p if isinstance(p, str) else _nodo_en(m, p) for p in puntos]
    if len(set(ids)) != 4:
        raise ValueError("las cuatro esquinas deben ser nodos distintos")
    for a in m.areas:
        if set(a.nodos) == set(ids):
            return a.id  # ya existe: no se duplica
    if tipo is None:
        tipo = "losa" if all(math.isclose(m.nodo(n).z, m.nodo(ids[0]).z, abs_tol=TOLERANCIA) for n in ids) else "muro"
    id_ = _siguiente("L" if tipo == "losa" else "M", (a.id for a in m.areas))
    m.areas.append(Area(id=id_, tipo=tipo, nodos=tuple(ids), seccion=seccion))
    return id_


def _sobre_segmento(p, a, b) -> bool:
    d = b - a
    t = float((p - a) @ d / (d @ d))
    return -1e-9 < t < 1 + 1e-9 and float(((a + t * d - p) ** 2).sum()) ** 0.5 < TOLERANCIA


def _borrar_nodos_sueltos(m: Edificio, candidatos: Iterable[str]) -> None:
    """Borra los nodos indicados que ya no usa ninguna barra, área, carga ni masa (con su apoyo)."""
    usados = {n for b in m.barras for n in (b.i, b.j)} | {n for a in m.areas for n in a.nodos}
    usados |= {o.nodo for o in (*m.cargas_nodales, *m.masas_nodales)}
    quitar = set(candidatos) - usados
    m.nodos = [n for n in m.nodos if n.id not in quitar]
    m.apoyos = [a for a in m.apoyos if a.nodo not in quitar]


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
