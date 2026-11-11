"""Edición del modelo en la ventana: selección, dibujo con clics, propiedades y diálogos.

Es una mezcla (mixin) de `VentanaPrincipal`. Cada acción de un diálogo termina en un método
`hacer_*` o `clic` que no abre ventanas, para poder probar el flujo sin pantalla.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDockWidget,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ..modelo import EspectroNTC, Rejilla
from ..modelo.edicion import ARTICULADO, EMPOTRADO, TOLERANCIA
from . import definiciones as dfn
from .dialogos import Campo, DialogoFormulario, DialogoRejilla, DialogoTabla

MODOS = {
    "seleccionar": "Seleccionar", "barra": "Dibujar barra", "columna": "Dibujar columna",
    "muro": "Dibujar muro", "losa": "Dibujar losa",
}
APOYOS = {"Libre": None, "Empotrado": EMPOTRADO, "Articulado": ARTICULADO}
_GDL = ("UX", "UY", "UZ", "RX", "RY", "RZ")
_TITULOS_DEFINIR = {
    "materiales": "Materiales",
    "secciones": "Secciones de barra",
    "secciones_area": "Secciones de muro y losa",
    "patrones": "Patrones de carga",
    "combinaciones": "Combinaciones de carga",
    "mamposteria": "Propiedades de mampostería (NTC)",
    "refuerzo_muros": "Refuerzo de muros de mampostería (NTC)",
}


_CAMPOS_MURO = ("muro_x1", "muro_y1", "muro_x2", "muro_y2", "muro_z0", "muro_z1")
_ETIQUETAS_MURO = ("X inicio (m)", "Y inicio (m)", "X fin (m)", "Y fin (m)", "Z base (m)", "Z corona (m)")


def geometria_muro(modelo, area) -> tuple[float, ...] | None:
    """(x1, y1, x2, y2, z base, z corona) de un muro vertical rectangular; None si no lo es."""
    if area.tipo != "muro":
        return None
    c = modelo.esquinas(area)
    (a, b, d, e) = c
    vertical = all(math.isclose(p[0], q[0], abs_tol=TOLERANCIA) and math.isclose(p[1], q[1], abs_tol=TOLERANCIA) for p, q in ((a, e), (b, d)))
    plano = math.isclose(a[2], b[2], abs_tol=TOLERANCIA) and math.isclose(d[2], e[2], abs_tol=TOLERANCIA)
    if not (vertical and plano and a[2] < e[2]):
        return None
    return (float(a[0]), float(a[1]), float(b[0]), float(b[1]), float(a[2]), float(e[2]))


def nombre_apoyo(restricciones) -> str:
    for nombre, r in APOYOS.items():
        if r is not None and tuple(restricciones) == r:
            return nombre
    return "Personalizado (" + " ".join(g for g, x in zip(_GDL, restricciones) if x) + ")"


class EdicionMixin:
    # --- construcción -----------------------------------------------------------
    def _crear_edicion(self) -> None:
        self.sel_nodos: set[str] = set()
        self.sel_barras: set[str] = set()
        self.sel_areas: set[str] = set()
        self.modo = "seleccionar"
        self.primer_punto: str | tuple[float, float, float] | None = None
        self._refrescando_arbol = False

        # Explorador del modelo (izquierda): otra forma de seleccionar
        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.arbol.itemSelectionChanged.connect(self._seleccion_desde_arbol)
        dock = QDockWidget("Explorador", self)
        dock.setWidget(self.arbol)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # Propiedades de lo seleccionado (izquierda, abajo del explorador)
        self.panel_propiedades = QScrollArea()
        self.panel_propiedades.setWidgetResizable(True)
        dock_p = QDockWidget("Propiedades", self)
        dock_p.setWidget(self.panel_propiedades)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_p)
        self.resizeDocks([dock, dock_p], [260, 260], Qt.Horizontal)

        self.sesion.editor.observadores.append(self._modelo_cambiado)

    def _crear_acciones_edicion(self) -> None:
        def accion(texto, funcion, atajo=None, menu=None):
            a = QAction(texto, self, triggered=funcion)
            if atajo:
                a.setShortcut(atajo)
            if menu is not None:
                menu.addAction(a)
            return a

        mb = self.menuBar()
        menu_editar = mb.addMenu("&Editar")
        self.accion_deshacer = accion("Deshacer", self.deshacer, QKeySequence.Undo, menu_editar)
        self.accion_rehacer = accion("Rehacer", self.rehacer, QKeySequence.Redo, menu_editar)
        menu_editar.addSeparator()
        self.accion_borrar = accion("Borrar selección", self.borrar_seleccion, QKeySequence.Delete, menu_editar)
        self.accion_sel_todo = accion("Seleccionar todo", self.seleccionar_todo, QKeySequence.SelectAll, menu_editar)
        self.accion_sel_nada = accion("Quitar selección", lambda: self.seleccionar(), None, menu_editar)
        menu_editar.addSeparator()
        self.accion_replicar = accion("Replicar selección…", self._dialogo_replicar, "Ctrl+R", menu_editar)
        self.accion_dividir = accion("Dividir muro o losa…", self._dialogo_dividir, None, menu_editar)

        menu_def = mb.addMenu("&Definir")
        self.accion_rejilla = accion("Rejilla (ejes y niveles)…", self._dialogo_rejilla, None, menu_def)
        menu_def.addSeparator()
        self.acciones_definir = {c: accion(f"{t}…", lambda _=False, c=c: self._dialogo_definir(c), None, menu_def) for c, t in _TITULOS_DEFINIR.items()}
        menu_def.addSeparator()
        self.accion_masa = accion("Fuente de masa…", self._dialogo_masa, None, menu_def)
        self.accion_espectro = accion("Espectro NTC…", self._dialogo_espectro, None, menu_def)
        self.accion_malla = accion("Tamaño de malla de muros y losas…", self._dialogo_malla, None, menu_def)

        menu_dib = mb.addMenu("Di&bujar")
        self.grupo_modos = QActionGroup(self)
        self.acciones_modo = {}
        for clave, texto in MODOS.items():
            a = QAction(texto, self, checkable=True, triggered=lambda _=False, k=clave: self.fijar_modo(k))
            self.grupo_modos.addAction(a)
            menu_dib.addAction(a)
            self.acciones_modo[clave] = a
        self.acciones_modo["seleccionar"].setChecked(True)
        self.acciones_modo["seleccionar"].setShortcut(Qt.Key_Escape)
        menu_dib.addSeparator()
        self.accion_losas = accion("Losas en todos los tableros…", self._dialogo_losas, None, menu_dib)
        self.accion_nodo = accion("Nodo por coordenadas…", self._dialogo_nodo, None, menu_dib)
        self.accion_barra_sel = accion("Barra entre los dos nodos seleccionados", self.barra_entre_seleccionados, None, menu_dib)
        self.accion_marco = accion("Marco completo desde la rejilla…", self._dialogo_marco, None, menu_dib)

        menu_asig = mb.addMenu("A&signar")
        self.accion_apoyo = accion("Apoyo a nodos…", self._dialogo_apoyo, None, menu_asig)
        self.accion_carga_nodal = accion("Carga en nodos…", self._dialogo_carga_nodal, None, menu_asig)
        self.accion_seccion = accion("Sección a barras…", self._dialogo_seccion, None, menu_asig)
        self.accion_carga_dist = accion("Carga distribuida en barras…", self._dialogo_carga_distribuida, None, menu_asig)
        menu_asig.addSeparator()
        self.accion_seccion_area = accion("Sección a muros y losas…", self._dialogo_seccion_area, None, menu_asig)
        self.accion_carga_area = accion("Carga en muros y losas…", self._dialogo_carga_area, None, menu_asig)
        menu_asig.addSeparator()
        self.accion_diafragmas = accion("Diafragmas rígidos por nivel…", self._dialogo_diafragmas, None, menu_asig)

        # Barra de herramientas de dibujo
        barra = QToolBar("Dibujo", self)
        self.addToolBarBreak()
        self.addToolBar(barra)
        barra.addAction(self.accion_deshacer)
        barra.addAction(self.accion_rehacer)
        barra.addSeparator()
        for a in self.acciones_modo.values():
            barra.addAction(a)
        barra.addWidget(QLabel(" Sección: "))
        self.selector_seccion = QComboBox()
        self.selector_seccion.setMinimumWidth(110)
        self.selector_seccion.setToolTip("Sección de las barras que se dibujan")
        barra.addWidget(self.selector_seccion)
        barra.addWidget(QLabel(" Muro/losa: "))
        self.selector_seccion_area = QComboBox()
        self.selector_seccion_area.setMinimumWidth(130)
        self.selector_seccion_area.setToolTip("Sección de los muros y losas que se dibujan")
        barra.addWidget(self.selector_seccion_area)
        barra.addSeparator()
        barra.addAction(self.accion_borrar)
        barra.addAction(self.accion_apoyo)
        barra.addAction(self.accion_carga_dist)

        self._acciones_con_modelo = [
            self.accion_borrar, self.accion_sel_todo, self.accion_sel_nada, self.accion_rejilla,
            *self.acciones_definir.values(), self.accion_masa, self.accion_espectro, *self.acciones_modo.values(),
            self.accion_nodo, self.accion_barra_sel, self.accion_marco, self.accion_apoyo, self.accion_carga_nodal,
            self.accion_seccion, self.accion_carga_dist, self.accion_malla, self.accion_losas,
            self.accion_seccion_area, self.accion_carga_area, self.accion_replicar, self.accion_dividir,
            self.accion_diafragmas,
        ]

    # --- cambios del modelo -------------------------------------------------------
    def editar(self, funcion, *args, **kwargs):
        """Ejecuta una operación del editor; si falla, muestra el error y no cambia nada."""
        try:
            return funcion(*args, **kwargs)
        except (ValueError, KeyError) as e:
            self._error(f"No se pudo editar el modelo:\n{e}")
            return None

    def _modelo_cambiado(self) -> None:
        m = self.sesion.modelo
        if m is None:
            self.sel_nodos.clear()
            self.sel_barras.clear()
            self.sel_areas.clear()
        else:
            self.sel_nodos &= {n.id for n in m.nodos}
            self.sel_barras &= {b.id for b in m.barras}
            self.sel_areas &= {a.id for a in m.areas}
        if isinstance(self.primer_punto, str) and (m is None or self.primer_punto not in {n.id for n in m.nodos}):
            self.primer_punto = None
        self._actualizar_estado()
        self._llenar_arbol()
        self._actualizar_propiedades()
        self.actualizar_vista()
        self._mensaje_seleccion()

    def _actualizar_estado_edicion(self) -> None:
        ed = self.sesion.editor
        hay = self.sesion.modelo is not None
        self.accion_deshacer.setEnabled(ed.puede_deshacer)
        self.accion_rehacer.setEnabled(ed.puede_rehacer)
        self.accion_deshacer.setText(f"Deshacer {ed.texto_deshacer.lower()}".strip())
        self.accion_rehacer.setText(f"Rehacer {ed.texto_rehacer.lower()}".strip())
        for a in self._acciones_con_modelo:
            a.setEnabled(hay)
        for selector, coleccion in ((self.selector_seccion, "secciones"), (self.selector_seccion_area, "secciones_area")):
            actual = selector.currentText()
            selector.clear()
            if hay:
                nombres = [s.nombre for s in getattr(self.sesion.modelo, coleccion)]
                selector.addItems(nombres)
                if actual in nombres:
                    selector.setCurrentText(actual)

    def deshacer(self) -> None:
        desc = self.sesion.editor.deshacer()
        if desc:
            self.log(f"Deshecho: {desc}")

    def rehacer(self) -> None:
        desc = self.sesion.editor.rehacer()
        if desc:
            self.log(f"Rehecho: {desc}")

    # --- selección ----------------------------------------------------------------
    def seleccionar(self, nodos=(), barras=(), aditivo: bool = False, areas=()) -> None:
        if aditivo:
            # Con Ctrl o Mayús, un clic sobre algo ya seleccionado lo quita
            self.sel_nodos ^= set(nodos)
            self.sel_barras ^= set(barras)
            self.sel_areas ^= set(areas)
        else:
            self.sel_nodos, self.sel_barras, self.sel_areas = set(nodos), set(barras), set(areas)
        self._seleccion_cambiada()

    def seleccionar_todo(self) -> None:
        m = self.sesion.modelo
        if m is not None:
            self.seleccionar([n.id for n in m.nodos], [b.id for b in m.barras], areas=[a.id for a in m.areas])

    def _seleccion_cambiada(self) -> None:
        self._sincronizar_arbol()
        self._actualizar_propiedades()
        self._dibujar_seleccion()
        self._mensaje_seleccion()

    def _mensaje_seleccion(self) -> None:
        n, b, a = len(self.sel_nodos), len(self.sel_barras), len(self.sel_areas)
        if n or b or a:
            texto = f"Seleccionados: {n} nodo{'s' * (n != 1)}, {b} barra{'s' * (b != 1)}"
            if a:
                texto += f", {a} muro{'s' * (a != 1)} o losa{'s' * (a != 1)}"
            self.statusBar().showMessage(texto)
        elif self.statusBar().currentMessage().startswith("Seleccionados:"):
            self.statusBar().clearMessage()

    def clic(self, objetivo: tuple[str, object] | None, aditivo: bool = False) -> None:
        """Clic en la vista: ("nodo", id), ("barra", id), ("area", id), ("punto", (x, y, z)) o None."""
        if self.sesion.modelo is None:
            return
        if self.modo == "seleccionar":
            if objetivo is None:
                if not aditivo:
                    self.seleccionar()
            elif objetivo[0] == "nodo":
                self.seleccionar(nodos=[objetivo[1]], aditivo=aditivo)
            elif objetivo[0] == "barra":
                self.seleccionar(barras=[objetivo[1]], aditivo=aditivo)
            elif objetivo[0] == "area":
                self.seleccionar(areas=[objetivo[1]], aditivo=aditivo)
            return
        if objetivo is None or objetivo[0] in ("barra", "area"):
            return
        punto = objetivo[1]
        if self.modo in ("muro", "losa"):
            return self._clic_area(punto)
        seccion = self.selector_seccion.currentText()
        if not seccion:
            self._error("Primero define una sección (Definir > Secciones).")
            return
        if self.modo == "barra":
            if self.primer_punto is None:
                self.primer_punto = punto
                self.log("Barra: elige el otro extremo (Esc para terminar)")
                self._dibujar_seleccion()
                return
            inicio, self.primer_punto = self.primer_punto, None
            id_ = self.editar(self.sesion.editor.agregar_barra, inicio, punto, seccion)
            if id_:
                # Sigue dibujando desde el extremo final, como en ETABS
                self.primer_punto = self._id_nodo_en(punto)
                self.log(f"Barra {id_} agregada")
        elif self.modo == "columna":
            x, y, z = self._coords(punto)
            abajo = self._nivel_abajo(z)
            if abajo is None:
                self.log("Columna: no hay un nivel abajo de ese punto")
                return
            ids = self.editar(self.sesion.editor.agregar_columnas, [(x, y)], abajo, z, seccion)
            if ids:
                self.log(f"Columna {ids[0]} agregada")

    def _clic_area(self, punto) -> None:
        """Muro: dos clics en el nivel de arriba, baja hasta el nivel de abajo.
        Losa: dos clics en esquinas opuestas del mismo nivel."""
        seccion = self.selector_seccion_area.currentText()
        if not seccion:
            self._error("Primero define una sección de muro o losa (Definir > Secciones de muro y losa).")
            return
        if self.primer_punto is None:
            self.primer_punto = punto
            self.log("Muro: elige el otro extremo arriba" if self.modo == "muro" else "Losa: elige la esquina opuesta")
            self._dibujar_seleccion()
            return
        inicio, self.primer_punto = self.primer_punto, None
        (x1, y1, z1), (x2, y2, z2) = self._coords(inicio), self._coords(punto)
        if not math.isclose(z1, z2, abs_tol=TOLERANCIA):
            self._error("Los dos puntos deben estar en el mismo nivel.")
            return
        if self.modo == "muro":
            abajo = self._nivel_abajo(z1)
            if abajo is None:
                self._error("Muro: no hay un nivel abajo de esos puntos.")
                return
            id_ = self.editar(self.sesion.editor.agregar_muro, (x1, y1), (x2, y2), abajo, z1, seccion)
            if id_:
                # Sigue dibujando desde el extremo final, como en ETABS
                self.primer_punto = self._id_nodo_en(punto)
        else:
            id_ = self.editar(self.sesion.editor.agregar_losa, (x1, y1), (x2, y2), z1, seccion)
        if id_:
            self.log(f"Muro {id_} agregado" if self.modo == "muro" else f"Losa {id_} agregada")
        self._dibujar_seleccion()

    def fijar_modo(self, modo: str) -> None:
        self.modo = modo
        self.primer_punto = None
        self.acciones_modo[modo].setChecked(True)
        ayuda = {
            "seleccionar": "Clic para seleccionar; Ctrl o Mayús para agregar o quitar.",
            "barra": "Clic en dos nodos o cruces de la rejilla para dibujar una barra; Esc para terminar.",
            "columna": "Clic en un cruce de la rejilla para poner una columna hasta el nivel de abajo.",
            "muro": "Clic en dos puntos de un nivel: el muro baja de ahí al nivel de abajo. Esc para terminar.",
            "losa": "Clic en dos esquinas opuestas de un tablero, en el mismo nivel.",
        }[modo]
        self.statusBar().showMessage(ayuda)
        self.actualizar_vista()

    def _coords(self, punto) -> tuple[float, float, float]:
        if isinstance(punto, str):
            n = self.sesion.modelo.nodo(punto)
            return n.x, n.y, n.z
        return tuple(float(v) for v in punto)

    def _id_nodo_en(self, punto) -> str | None:
        if isinstance(punto, str):
            return punto
        for n in self.sesion.modelo.nodos:
            if all(math.isclose(a, b, abs_tol=TOLERANCIA) for a, b in zip((n.x, n.y, n.z), punto)):
                return n.id
        return None

    def _nivel_abajo(self, z: float) -> float | None:
        m = self.sesion.modelo
        cotas = {nv.z for nv in m.rejilla.niveles} if m.rejilla else {n.z for n in m.nodos}
        abajo = [c for c in cotas if c < z - TOLERANCIA]
        return max(abajo) if abajo else None

    def borrar_seleccion(self) -> None:
        if not (self.sel_nodos or self.sel_barras or self.sel_areas):
            return
        n, b, a = len(self.sel_nodos), len(self.sel_barras), len(self.sel_areas)
        try:
            self.sesion.editor.borrar(self.sel_nodos, self.sel_barras, self.sel_areas)
        except ValueError as e:
            return self._error(f"No se pudo borrar:\n{e}")
        self.log(f"Borrados {n} nodos, {b} barras y {a} muros o losas, con sus cargas y apoyos (Ctrl+Z para deshacer)")

    def barra_entre_seleccionados(self) -> None:
        if len(self.sel_nodos) != 2 or self.sel_barras:
            self._error("Selecciona exactamente dos nodos.")
            return
        i, j = sorted(self.sel_nodos)
        id_ = self.editar(self.sesion.editor.agregar_barra, i, j, self.selector_seccion.currentText())
        if id_:
            self.seleccionar(barras=[id_])

    # --- explorador ----------------------------------------------------------------
    def _llenar_arbol(self) -> None:
        self._refrescando_arbol = True
        self.arbol.clear()
        m = self.sesion.modelo
        self._items_arbol: dict[tuple[str, str], QTreeWidgetItem] = {}
        if m is not None:
            grupos = [("nodo", "Nodos", [n.id for n in m.nodos]), ("barra", "Barras", [b.id for b in m.barras])]
            if m.areas:
                grupos.append(("area", "Muros y losas", [a.id for a in m.areas]))
            for clave, titulo, ids in grupos:
                raiz = QTreeWidgetItem([f"{titulo} ({len(ids)})"])
                raiz.setFlags(raiz.flags() & ~Qt.ItemIsSelectable)
                self.arbol.addTopLevelItem(raiz)
                for i in ids:
                    it = QTreeWidgetItem([i])
                    it.setData(0, Qt.UserRole, (clave, i))
                    raiz.addChild(it)
                    self._items_arbol[(clave, i)] = it
        self._refrescando_arbol = False
        self._sincronizar_arbol()

    def _sincronizar_arbol(self) -> None:
        self._refrescando_arbol = True
        for (clave, i), it in getattr(self, "_items_arbol", {}).items():
            it.setSelected(i in {"nodo": self.sel_nodos, "barra": self.sel_barras, "area": self.sel_areas}[clave])
        self._refrescando_arbol = False

    def _seleccion_desde_arbol(self) -> None:
        if self._refrescando_arbol:
            return
        datos = [it.data(0, Qt.UserRole) for it in self.arbol.selectedItems()]
        self.sel_nodos = {i for c, i in datos if c == "nodo"}
        self.sel_barras = {i for c, i in datos if c == "barra"}
        self.sel_areas = {i for c, i in datos if c == "area"}
        self._actualizar_propiedades()
        self._dibujar_seleccion()

    # --- propiedades ---------------------------------------------------------------
    def _actualizar_propiedades(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.controles_propiedades: dict[str, QWidget] = {}
        m = self.sesion.modelo
        if m is None:
            form.addRow(QLabel("Sin modelo. Archivo > Nuevo para empezar."))
        elif len(self.sel_nodos) == 1 and not self.sel_barras and not self.sel_areas:
            n = m.nodo(next(iter(self.sel_nodos)))
            form.addRow(QLabel("<b>Nodo</b>"))
            self._fila_texto(form, "id", "Id", n.id)
            for c in "xyz":
                self._fila_texto(form, c, f"{c.upper()} (m)", f"{getattr(n, c):g}")
            self._fila_apoyo(form, [n.id])
            cargas = [f"{c.patron}: " + ", ".join(f"{g}={v:g}" for g, v in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"), c.fuerzas) if v) for c in m.cargas_nodales if c.nodo == n.id]
            form.addRow("Cargas", QLabel("\n".join(cargas) or "ninguna"))
        elif len(self.sel_barras) == 1 and not self.sel_nodos and not self.sel_areas:
            b = m.barra(next(iter(self.sel_barras)))
            form.addRow(QLabel("<b>Barra</b>"))
            self._fila_texto(form, "id", "Id", b.id)
            self._fila_combo(form, "tipo", "Tipo", ["columna", "viga", "contraviento", "barra"], b.tipo)
            form.addRow("Nodos", QLabel(f"{b.i} → {b.j}"))
            self._fila_combo(form, "seccion", "Sección", [s.nombre for s in m.secciones], b.seccion)
            self._fila_texto(form, "rotacion", "Rotación (°)", f"{b.rotacion:g}")
            form.addRow("Longitud (m)", QLabel(f"{m.longitud(b):.3f}"))
            cargas = [f"{c.patron}: w{c.direccion} = {c.w:g} kN/m" for c in m.cargas_distribuidas if c.barra == b.id]
            form.addRow("Cargas", QLabel("\n".join(cargas) or "ninguna"))
        elif len(self.sel_areas) == 1 and not self.sel_nodos and not self.sel_barras:
            a = m.area(next(iter(self.sel_areas)))
            form.addRow(QLabel(f"<b>{'Muro' if a.tipo == 'muro' else 'Losa'}</b>"))
            self._fila_texto(form, "id", "Id", a.id)
            self._fila_combo(form, "seccion_area", "Sección", [s.nombre for s in m.secciones_area], a.seccion)
            form.addRow("Nodos", QLabel(" → ".join(a.nodos)))
            form.addRow("Área (m²)", QLabel(f"{m.superficie(a):.3f}"))
            s = m.seccion_area(a.seccion)
            form.addRow("Espesor (m)", QLabel(f"{s.espesor:g}"))
            geo = geometria_muro(m, a)
            if geo is not None:
                for campo, etiqueta, valor in zip(_CAMPOS_MURO, _ETIQUETAS_MURO, geo):
                    self._fila_texto(form, campo, etiqueta, f"{valor:g}")
            cargas = [f"{c.patron}: w{c.direccion} = {c.w:g} kN/m²" for c in m.cargas_area if c.area == a.id]
            form.addRow("Cargas", QLabel("\n".join(cargas) or "ninguna"))
        elif self.sel_nodos or self.sel_barras or self.sel_areas:
            form.addRow(QLabel(f"<b>{len(self.sel_nodos)} nodos, {len(self.sel_barras)} barras, {len(self.sel_areas)} muros y losas</b>"))
            if self.sel_nodos:
                self._fila_apoyo(form, sorted(self.sel_nodos))
            if self.sel_barras:
                secciones = {m.barra(i).seccion for i in self.sel_barras}
                actual = secciones.pop() if len(secciones) == 1 else "(varias)"
                opciones = [s.nombre for s in m.secciones] + ([actual] if actual == "(varias)" else [])
                self._fila_combo(form, "seccion", "Sección", opciones, actual)
            if self.sel_areas:
                secciones = {m.area(i).seccion for i in self.sel_areas}
                actual = secciones.pop() if len(secciones) == 1 else "(varias)"
                opciones = [s.nombre for s in m.secciones_area] + ([actual] if actual == "(varias)" else [])
                self._fila_combo(form, "seccion_area", "Sección de área", opciones, actual)
        else:
            form.addRow(QLabel("<b>Modelo</b>"))
            self._fila_texto(form, "nombre_modelo", "Nombre", m.nombre)
            form.addRow("Nodos", QLabel(str(len(m.nodos))))
            form.addRow("Barras", QLabel(str(len(m.barras))))
            form.addRow("Apoyos", QLabel(str(len(m.apoyos))))
            if m.areas:
                form.addRow("Muros y losas", QLabel(str(len(m.areas))))
            form.addRow(QLabel("Selecciona algo en la vista o en el explorador para editarlo."))
        self.panel_propiedades.setWidget(w)

    def _fila_texto(self, form, campo, etiqueta, valor) -> None:
        e = QLineEdit(valor)
        # Diferido: el panel se reconstruye al cambiar el modelo y no conviene borrar el control
        # mientras emite su señal.
        e.editingFinished.connect(lambda: QTimer.singleShot(0, lambda: self.aplicar_propiedad(campo, e.text())))
        form.addRow(etiqueta, e)
        self.controles_propiedades[campo] = e

    def _fila_combo(self, form, campo, etiqueta, opciones, valor) -> None:
        c = QComboBox()
        c.addItems(opciones)
        c.setCurrentText(valor)
        c.currentTextChanged.connect(lambda t: QTimer.singleShot(0, lambda: self.aplicar_propiedad(campo, t)))
        form.addRow(etiqueta, c)
        self.controles_propiedades[campo] = c

    def _fila_apoyo(self, form, nodos) -> None:
        m = self.sesion.modelo
        por_nodo = {a.nodo: a.restricciones for a in m.apoyos}
        nombres = {nombre_apoyo(por_nodo[n]) if n in por_nodo else "Libre" for n in nodos}
        actual = nombres.pop() if len(nombres) == 1 else "(varios)"
        opciones = list(APOYOS) + ([actual] if actual not in APOYOS else [])
        self._fila_combo(form, "apoyo", "Apoyo", opciones, actual)

    def aplicar_propiedad(self, campo: str, valor: str) -> None:
        """Aplica un cambio hecho en el panel de propiedades a lo seleccionado."""
        m = self.sesion.modelo
        if m is None:
            return
        ed = self.sesion.editor
        valor = valor.strip()
        try:
            if campo == "nombre_modelo":
                if valor and valor != m.nombre:
                    ed.renombrar_modelo(valor)
            elif campo == "apoyo":
                if valor in APOYOS and self.sel_nodos:
                    ed.asignar_apoyo(self.sel_nodos, APOYOS[valor])
            elif campo == "seccion_area":
                if valor in {s.nombre for s in m.secciones_area} and any(m.area(i).seccion != valor for i in self.sel_areas):
                    ed.asignar_seccion_area(self.sel_areas, valor)
            elif len(self.sel_areas) == 1 and not self.sel_nodos and not self.sel_barras:
                aid = next(iter(self.sel_areas))
                if campo == "id" and valor and valor != aid:
                    ed.editar_area(aid, id=valor)
                    self.sel_areas = {valor}
                    self._modelo_cambiado()
                elif campo in _CAMPOS_MURO:
                    geo = list(geometria_muro(m, m.area(aid)))
                    k = _CAMPOS_MURO.index(campo)
                    nuevo = dfn._float(valor)
                    if not math.isclose(nuevo, geo[k], abs_tol=TOLERANCIA):
                        geo[k] = nuevo
                        x1, y1, x2, y2, z0, z1 = geo
                        ed.editar_muro(aid, (x1, y1), (x2, y2), z0, z1)
            elif len(self.sel_nodos) == 1 and not self.sel_barras:
                nid = next(iter(self.sel_nodos))
                n = m.nodo(nid)
                if campo == "id" and valor and valor != nid:
                    ed.editar_nodo(nid, id_nuevo=valor)
                    self.sel_nodos = {valor}
                    self._modelo_cambiado()
                elif campo in "xyz" and not math.isclose(dfn._float(valor), getattr(n, campo)):
                    ed.editar_nodo(nid, **{campo: dfn._float(valor)})
            elif self.sel_barras and not self.sel_nodos:
                if campo == "seccion" and valor in {s.nombre for s in m.secciones}:
                    if any(m.barra(i).seccion != valor for i in self.sel_barras):
                        ed.asignar_seccion(self.sel_barras, valor)
                elif len(self.sel_barras) == 1:
                    bid = next(iter(self.sel_barras))
                    b = m.barra(bid)
                    if campo == "id" and valor and valor != bid:
                        ed.editar_barra(bid, id=valor)
                        self.sel_barras = {valor}
                        self._modelo_cambiado()
                    elif campo == "tipo" and valor != b.tipo:
                        ed.editar_barra(bid, tipo=valor)
                    elif campo == "rotacion" and not math.isclose(dfn._float(valor), b.rotacion):
                        ed.editar_barra(bid, rotacion=dfn._float(valor))
        except (ValueError, KeyError) as e:
            self._error(f"No se pudo cambiar {campo}:\n{e}")
            self._actualizar_propiedades()

    # --- archivo nuevo -------------------------------------------------------------
    def nuevo_modelo(
        self, nombre: str, claros_x: list[float], claros_y: list[float], alturas: list[float],
        crear_marco: bool = True, diafragmas: bool = False,
    ) -> None:
        rejilla = Rejilla.regular(claros_x, claros_y, alturas)
        self.sesion.nuevo(nombre, rejilla)
        if diafragmas:
            self.sesion.editor.asignar_diafragmas([nv.nombre for nv in rejilla.niveles[1:]])
        if crear_marco:
            m = self.sesion.modelo
            n = self.sesion.editor.marco_desde_rejilla(m.secciones[0].nombre, m.secciones[1].nombre)
            self.log(f"Modelo nuevo «{nombre}»: {n} barras en la rejilla, con apoyos empotrados en la base")
        else:
            self.log(f"Modelo nuevo «{nombre}» con rejilla vacía")
        self.fijar_modo("seleccionar")
        self.actualizar_vista(reiniciar_camara=True)

    def _dialogo_nuevo(self) -> None:
        if not self._confirmar_descartar():
            return
        d = DialogoFormulario(
            "Modelo nuevo",
            [
                Campo("nombre", "Nombre", "Edificio"),
                Campo("x", "Claros en X (m)", "3x6", ayuda="Separados por comas; «3x6» son tres claros de 6 m"),
                Campo("y", "Claros en Y (m)", "2x5"),
                Campo("h", "Alturas de entrepiso (m)", "3.5, 2x3"),
                Campo("marco", "Crear columnas, vigas y apoyos", True),
                Campo("diafragmas", "Diafragma rígido en cada nivel", True),
            ],
            self,
            nota="Se crea la rejilla de ejes y niveles. Material, secciones, patrones y combinaciones "
            "son de partida: edítalos en el menú Definir.",
        )
        if d.exec() != QDialog.Accepted:
            return
        v = d.valores()
        try:
            self.nuevo_modelo(v["nombre"] or "Edificio", dfn.leer_lista(v["x"]), dfn.leer_lista(v["y"]), dfn.leer_lista(v["h"]), v["marco"], v["diafragmas"])
        except ValueError as e:
            self._error(f"No se pudo crear el modelo:\n{e}")

    # --- Definir --------------------------------------------------------------------
    def _dialogo_rejilla(self) -> None:
        d = DialogoRejilla(self.sesion.modelo.rejilla, self)
        if d.exec() == QDialog.Accepted:
            self.editar(self.sesion.editor.definir_rejilla, d.rejilla())

    def hacer_definir(self, coleccion: str, filas: list[list[str]], renombres: dict[str, str] | None = None) -> None:
        """Reemplaza una colección con filas de texto; lanza ValueError si no es válida."""
        m = self.sesion.modelo
        objetos = dfn.objetos(coleccion, filas, m, renombres)
        if coleccion in dfn.COLECCION_DEL_MODELO:
            self.sesion.editor.reemplazar(dfn.COLECCION_DEL_MODELO[coleccion], objetos)
        else:
            self.sesion.editor.reemplazar(coleccion, objetos, renombres)

    def _dialogo_definir(self, coleccion: str) -> None:
        m = self.sesion.modelo
        d = DialogoTabla(
            _TITULOS_DEFINIR[coleccion], dfn.columnas(coleccion, m), dfn.filas(coleccion, m),
            validar=lambda f, r: self.hacer_definir(coleccion, f, r), parent=self,
            nota="Al renombrar, el nuevo nombre se aplica en todo el modelo. "
            + {
                "secciones": "Las secciones rectangulares solo usan b y h; las generales, A, I33, I22 y J.",
                "secciones_area": "Mod. rigidez multiplica E en membrana y flexión (p. ej. 0.5 para muros agrietados). "
                "Mod. cortante multiplica además el módulo de cortante en el plano (0.5 en muros de mampostería "
                "agrietados, NTC Mampostería 3.1.1.2.3). En mampostería G = 0.2·E (2.8.6.4.1).",
                "mamposteria": "Una fila por material de tipo mampostería. f'm y v'm de diseño sobre área bruta "
                "(ensayes de pilas y muretes, 2.8.1 y 2.8.2). Si se deja f'm vacío y se da f'p, f'm sale de las "
                "tablas 2.8.1.4.1 o 2.8.1.4.2. Sin fila se usan los valores de las tablas 12.2.3 (Tipo II).",
                "refuerzo_muros": "Una fila por sección de muro de mampostería. Castillos externos en los extremos e "
                "intersecciones; refuerzo horizontal Ash cada sh (vacío o 0 = sin refuerzo). pv·fyv y fnm solo para "
                "muros reforzados interiormente. Sin fila: confinado, castillos 15 × 15 con 4 #3.",
            }.get(coleccion, ""),
        )
        d.exec()

    def _dialogo_masa(self) -> None:
        m = self.sesion.modelo
        d = DialogoFormulario(
            "Fuente de masa",
            [
                Campo("fuente", "Patrones y factores", dfn.formatear_factores(m.fuente_masa), ayuda="p. ej. 1*CM + 0.4*CV"),
                Campo("pp", "Incluir peso propio de barras, muros y losas", m.peso_propio_en_masa),
            ],
            self,
            nota="Con la casilla marcada el peso propio entra completo y no se vuelve a sumar "
            "por los patrones que lo aplican como carga.",
        )
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            try:
                fuente = dfn.leer_factores(v["fuente"]) if v["fuente"].strip() else {}
            except ValueError as e:
                return self._error(str(e))
            self.editar(self.sesion.editor.definir_masa, fuente, v["pp"])

    def _dialogo_espectro(self) -> None:
        e = self.sesion.modelo.espectro
        base = e if isinstance(e, EspectroNTC) else EspectroNTC(nombre="Espectro NTC", a0=0.1, c=0.3, Ta=0.4, Tb=1.2, k=1.0)
        campos = [Campo("usar", "Usar espectro", e is not None), Campo("nombre", "Nombre", base.nombre)]
        campos += [Campo(k, k, float(getattr(base, k))) for k in ("a0", "c", "Ta", "Tb", "k", "beta", "reduccion")]
        nota = "Parámetros que entrega SASID (g y s). «reduccion» divide las ordenadas, p. ej. Q'·R."
        if e is not None and not isinstance(e, EspectroNTC):
            nota += " El modelo tiene un espectro tabular; si aceptas, se reemplaza."
        d = DialogoFormulario("Espectro de diseño", campos, self, nota=nota)
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            if not v.pop("usar"):
                return self.editar(self.sesion.editor.definir_espectro, None)
            try:
                esp = EspectroNTC(**v)
            except ValueError as err:
                return self._error(str(err))
            self.editar(self.sesion.editor.definir_espectro, esp)

    def _dialogo_malla(self) -> None:
        m = self.sesion.modelo
        d = DialogoFormulario(
            "Malla de muros y losas", [Campo("t", "Tamaño máximo de elemento (m)", float(m.tamano_malla))], self,
            nota="Cada muro y losa se divide en elementos de cáscara de este tamaño o menores. "
            "Más fino es más preciso y más lento; 0.5 a 1 m suele bastar en edificios.",
        )
        if d.exec() == QDialog.Accepted:
            self.editar(self.sesion.editor.definir_malla, d.valores()["t"])

    # --- Dibujar --------------------------------------------------------------------
    def _dialogo_losas(self) -> None:
        m = self.sesion.modelo
        nombres = [s.nombre for s in m.secciones_area if s.tipo == "losa"] or [s.nombre for s in m.secciones_area]
        if m.rejilla is None or not nombres:
            return self._error("Hace falta una rejilla (Definir > Rejilla) y una sección de losa.")
        d = DialogoFormulario(
            "Losas desde la rejilla", [Campo("s", "Sección de losa", nombres[0], nombres)], self,
            nota="Pone una losa en cada tablero de la rejilla, en todos los niveles sobre la base. Lo que ya existe no se duplica.",
        )
        if d.exec() == QDialog.Accepted:
            n = self.editar(self.sesion.editor.losas_desde_rejilla, d.valores()["s"])
            if n is not None:
                self.log(f"Losas desde rejilla: {n} losas nuevas")

    def _dialogo_nodo(self) -> None:
        d = DialogoFormulario("Nodo por coordenadas", [Campo("x", "X (m)", 0.0), Campo("y", "Y (m)", 0.0), Campo("z", "Z (m)", 0.0)], self)
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            nid = self.editar(self.sesion.editor.agregar_nodo, v["x"], v["y"], v["z"])
            if nid:
                self.seleccionar(nodos=[nid])

    def _dialogo_marco(self) -> None:
        m = self.sesion.modelo
        nombres = [s.nombre for s in m.secciones]
        if m.rejilla is None or not nombres:
            return self._error("Hace falta una rejilla (Definir > Rejilla) y al menos una sección.")
        d = DialogoFormulario(
            "Marco desde la rejilla",
            [
                Campo("col", "Sección de columnas", nombres[0], nombres),
                Campo("viga", "Sección de vigas", nombres[min(1, len(nombres) - 1)], nombres),
                Campo("apoyos", "Empotrar los nodos de la base", True),
            ],
            self,
            nota="Pone columnas en cada cruce de ejes y vigas sobre cada eje, en todos los niveles. Lo que ya existe no se duplica.",
        )
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            n = self.editar(self.sesion.editor.marco_desde_rejilla, v["col"], v["viga"], apoyos_en_base=v["apoyos"])
            if n is not None:
                self.log(f"Marco desde rejilla: {n} barras nuevas")

    # --- Replicar y dividir --------------------------------------------------------------
    def _dialogo_replicar(self) -> None:
        if not (self.sel_nodos or self.sel_barras or self.sel_areas):
            return self._error("Selecciona primero lo que quieres replicar.")
        m = self.sesion.modelo
        niveles = [nv.nombre for nv in m.rejilla.niveles] if m.rejilla else []
        campos = [Campo("modo", "Modo", "A niveles" if niveles else "Lineal", ["A niveles", "Lineal"] if niveles else ["Lineal"])]
        if niveles:
            origen = self._nivel_de_seleccion() or niveles[min(1, len(niveles) - 1)]
            campos.append(Campo("origen", "Nivel de origen", origen, niveles))
            campos += [Campo(f"nv:{n}", f"Copiar a {n}", False) for n in niveles]
        campos += [
            Campo("dx", "dX (m)", 0.0), Campo("dy", "dY (m)", 0.0), Campo("dz", "dZ (m)", 0.0),
            Campo("veces", "Número de copias", 1.0),
            Campo("cargas", "Copiar cargas, apoyos y masas", True),
        ]
        d = DialogoFormulario(
            "Replicar selección", campos, self,
            nota="A niveles: copia lo seleccionado del nivel de origen a los niveles marcados (solo cambia Z). "
            "Lineal: copia «Número de copias» veces, desplazando dX, dY, dZ cada vez. "
            "Lo que ya existe en el destino no se duplica.",
        )
        if d.exec() != QDialog.Accepted:
            return
        v = d.valores()
        if v["modo"] == "A niveles":
            destinos = [n for n in niveles if v.get(f"nv:{n}")]
            self.hacer_replicar_a_niveles(v["origen"], destinos, v["cargas"])
        else:
            self.hacer_replicar((v["dx"], v["dy"], v["dz"]), int(round(v["veces"])), v["cargas"])

    def _nivel_de_seleccion(self) -> str | None:
        """Nivel de la rejilla donde está lo más alto de la selección (para proponer el origen)."""
        m = self.sesion.modelo
        zs = [m.nodo(n).z for n in self.sel_nodos]
        zs += [max(m.nodo(b.i).z, m.nodo(b.j).z) for b in m.barras if b.id in self.sel_barras]
        zs += [max(m.nodo(n).z for n in a.nodos) for a in m.areas if a.id in self.sel_areas]
        if not zs or m.rejilla is None:
            return None
        z = max(zs)
        return next((nv.nombre for nv in m.rejilla.niveles if math.isclose(nv.z, z, abs_tol=TOLERANCIA)), None)

    def hacer_replicar(self, paso: tuple[float, float, float], veces: int = 1, con_cargas: bool = True) -> None:
        if veces < 1:
            return self._error("El número de copias debe ser al menos 1.")
        desplazamientos = [tuple(k * v for v in paso) for k in range(1, veces + 1)]
        n = self.editar(self.sesion.editor.replicar, desplazamientos, self.sel_nodos, self.sel_barras, self.sel_areas, con_cargas)
        if n is not None:
            self.log(f"Replicar: {n['nodos']} nodos, {n['barras']} barras y {n['areas']} muros o losas nuevos")

    def hacer_replicar_a_niveles(self, origen: str, destinos: list[str], con_cargas: bool = True) -> None:
        destinos = [d for d in destinos if d != origen]
        if not destinos:
            return self._error("Marca al menos un nivel de destino distinto del de origen.")
        n = self.editar(self.sesion.editor.replicar_a_niveles, origen, destinos, self.sel_nodos, self.sel_barras, self.sel_areas, con_cargas)
        if n is not None:
            self.log(f"Replicar de {origen} a {', '.join(destinos)}: {n['nodos']} nodos, {n['barras']} barras y {n['areas']} muros o losas nuevos")

    def _dialogo_dividir(self) -> None:
        if len(self.sel_areas) != 1:
            return self._error("Selecciona un solo muro o losa.")
        aid = next(iter(self.sel_areas))
        a = self.sesion.modelo.area(aid)
        muro = a.tipo == "muro"
        d = DialogoFormulario(
            f"Dividir {aid}",
            [
                Campo("n1", "Partes a lo largo" if muro else "Partes en la dirección 1", 2.0),
                Campo("n2", "Partes a lo alto" if muro else "Partes en la dirección 2", 1.0),
            ],
            self,
            nota="Las piezas conservan la sección y las cargas. Sirve para abrir huecos (borrando una pieza) "
            "o para que el área se una con nodos intermedios.",
        )
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            self.hacer_dividir(aid, int(round(v["n1"])), int(round(v["n2"])))

    def hacer_dividir(self, area: str, partes_1: int, partes_2: int = 1) -> None:
        ids = self.editar(self.sesion.editor.dividir_area, area, partes_1, partes_2)
        if ids:
            self.seleccionar(areas=ids)
            self.log(f"{area} dividido en {len(ids)} partes: {', '.join(ids)}")

    # --- Asignar --------------------------------------------------------------------
    def _dialogo_diafragmas(self) -> None:
        m = self.sesion.modelo
        if m.rejilla is None or len(m.rejilla.niveles) < 2:
            return self._error("Hace falta una rejilla con niveles (Definir > Rejilla).")
        actuales = {d.nombre for d in m.diafragmas}
        niveles = m.rejilla.niveles[1:]
        d = DialogoFormulario(
            "Diafragmas rígidos",
            [Campo(nv.nombre, f"{nv.nombre} (z = {nv.z:g} m)", nv.nombre in actuales or not actuales) for nv in niveles],
            self,
            nota="Cada nivel marcado se mueve como cuerpo rígido en su plano (X, Y y giro): todos sus nodos, "
            "incluidos los de la malla de las losas. El nodo maestro va en el centro de masa del nivel. "
            "La flexión de las losas fuera de su plano no cambia.",
        )
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            self.hacer_diafragmas([nv.nombre for nv in niveles if v[nv.nombre]])

    def hacer_diafragmas(self, niveles: list[str]) -> None:
        """Deja diafragma rígido exactamente en los niveles indicados."""
        try:
            self.sesion.editor.asignar_diafragmas(niveles, solo_estos=True)
        except (ValueError, KeyError) as e:
            return self._error(f"No se pudo editar el modelo:\n{e}")
        self.log(f"Diafragmas rígidos en: {', '.join(niveles) or 'ningún nivel'}")


    def _exigir(self, nodos: bool = False, barras: bool = False, areas: bool = False) -> bool:
        if nodos and not self.sel_nodos:
            self._error("Selecciona uno o más nodos primero.")
            return False
        if barras and not self.sel_barras:
            self._error("Selecciona una o más barras primero.")
            return False
        if areas and not self.sel_areas:
            self._error("Selecciona uno o más muros o losas primero.")
            return False
        return True

    def _dialogo_seccion_area(self) -> None:
        if not self._exigir(areas=True):
            return
        nombres = [s.nombre for s in self.sesion.modelo.secciones_area]
        d = DialogoFormulario(f"Sección de {len(self.sel_areas)} muros o losas", [Campo("s", "Sección", nombres[0] if nombres else "", nombres)], self)
        if d.exec() == QDialog.Accepted:
            self.editar(self.sesion.editor.asignar_seccion_area, self.sel_areas, d.valores()["s"])

    def _dialogo_carga_area(self) -> None:
        if not self._exigir(areas=True):
            return
        campos = self._campos_patron() + [
            Campo("dir", "Dirección global", "Z", ["Z", "X", "Y"]),
            Campo("w", "w (kN/m²)", -2.0, ayuda="Negativo en Z es hacia abajo (gravedad)"),
            Campo("reemplazar", "Reemplazar las de ese patrón y dirección", True),
        ]
        d = DialogoFormulario(f"Carga en {len(self.sel_areas)} muros o losas", campos, self,
                              nota="Carga uniforme por m² de superficie, repartida a los nodos de la malla.")
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            self.hacer_carga_area(v["patron"], v["dir"], v["w"], v["reemplazar"])

    def hacer_carga_area(self, patron: str, direccion: str, w: float, reemplazar: bool = True) -> None:
        self.editar(self.sesion.editor.asignar_carga_area, self.sel_areas, patron, direccion, w, reemplazar)

    def _dialogo_apoyo(self) -> None:
        if not self._exigir(nodos=True):
            return
        campos = [Campo("tipo", "Tipo", "Empotrado", [*APOYOS, "Personalizado"])]
        campos += [Campo(g, f"Restringir {g}", True) for g in _GDL]
        d = DialogoFormulario(f"Apoyo en {len(self.sel_nodos)} nodos", campos, self, nota="Las casillas solo cuentan con el tipo Personalizado.")
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            r = tuple(v[g] for g in _GDL) if v["tipo"] == "Personalizado" else APOYOS[v["tipo"]]
            self.editar(self.sesion.editor.asignar_apoyo, self.sel_nodos, r)

    def _dialogo_seccion(self) -> None:
        if not self._exigir(barras=True):
            return
        nombres = [s.nombre for s in self.sesion.modelo.secciones]
        d = DialogoFormulario(f"Sección de {len(self.sel_barras)} barras", [Campo("s", "Sección", nombres[0] if nombres else "", nombres)], self)
        if d.exec() == QDialog.Accepted:
            self.editar(self.sesion.editor.asignar_seccion, self.sel_barras, d.valores()["s"])

    def _campos_patron(self) -> list[Campo]:
        nombres = [p.nombre for p in self.sesion.modelo.patrones]
        return [Campo("patron", "Patrón", nombres[0] if nombres else "", nombres)]

    def _dialogo_carga_nodal(self) -> None:
        if not self._exigir(nodos=True):
            return
        campos = self._campos_patron() + [Campo(g, f"{g} ({'kN' if g[0] == 'F' else 'kN·m'})", 0.0) for g in ("FX", "FY", "FZ", "MX", "MY", "MZ")]
        campos.append(Campo("reemplazar", "Reemplazar las de ese patrón", True))
        d = DialogoFormulario(f"Carga en {len(self.sel_nodos)} nodos", campos, self, nota="Ejes globales; Z hacia arriba (la gravedad es FZ negativa).")
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            self.hacer_carga_nodal(v["patron"], tuple(v[g] for g in ("FX", "FY", "FZ", "MX", "MY", "MZ")), v["reemplazar"])

    def hacer_carga_nodal(self, patron: str, fuerzas, reemplazar: bool = True) -> None:
        self.editar(self.sesion.editor.asignar_carga_nodal, self.sel_nodos, patron, fuerzas, reemplazar)

    def _dialogo_carga_distribuida(self) -> None:
        if not self._exigir(barras=True):
            return
        campos = self._campos_patron() + [
            Campo("dir", "Dirección global", "Z", ["Z", "X", "Y"]),
            Campo("w", "w (kN/m)", -10.0, ayuda="Negativo en Z es hacia abajo (gravedad)"),
            Campo("reemplazar", "Reemplazar las de ese patrón y dirección", True),
        ]
        d = DialogoFormulario(f"Carga distribuida en {len(self.sel_barras)} barras", campos, self)
        if d.exec() == QDialog.Accepted:
            v = d.valores()
            self.hacer_carga_distribuida(v["patron"], v["dir"], v["w"], v["reemplazar"])

    def hacer_carga_distribuida(self, patron: str, direccion: str, w: float, reemplazar: bool = True) -> None:
        self.editar(self.sesion.editor.asignar_carga_distribuida, self.sel_barras, patron, direccion, w, reemplazar)
