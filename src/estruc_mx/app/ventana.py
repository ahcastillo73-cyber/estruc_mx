"""Ventana principal: modelo 3D en el centro, explorador y propiedades a la izquierda,
tablas de resultados a la derecha y registro abajo."""

from __future__ import annotations

import sys
import traceback
from typing import Callable

import numpy as np

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .edicion import EdicionMixin
from .sesion import MOTORES, Sesion, Tabla

_VISTA_MODELO = "Modelo sin deformar"
_PREFIJO_CARGAS = "Cargas: "
_VISTA_MAMPOSTERIA = "Mampostería: demanda/capacidad"
_TABLAS_MAMPOSTERIA = ("Mampostería: muros", "Mampostería: revisiones", "Mampostería: entrepisos")
_COLOR_ESTADO = {"cumple": "#d8f0d2", "no cumple": "#f6d0cc"}


class _Senales(QObject):
    terminado = Signal(object)
    error = Signal(str)


class _Tarea(QRunnable):
    """Ejecuta un análisis fuera del hilo de la interfaz."""

    def __init__(self, funcion: Callable[[], object]):
        super().__init__()
        self.funcion = funcion
        self.senales = _Senales()

    def run(self) -> None:
        try:
            self.senales.terminado.emit(self.funcion())
        except Exception as e:  # noqa: BLE001 - se muestra al usuario
            self.senales.error.emit(f"{e}\n\n{traceback.format_exc(limit=3)}")


class VentanaPrincipal(EdicionMixin, QMainWindow):
    def __init__(self, vista_3d: bool = True, sincrono: bool = False):
        super().__init__()
        self.sesion = Sesion()
        self.sincrono = sincrono
        self._ocupado = False
        self.setWindowTitle("estruc_mx")
        self.resize(1400, 850)

        self._crear_vista(vista_3d)
        self._crear_paneles()
        self._crear_edicion()
        self._crear_acciones()
        self._modelo_cambiado()

    # --- construcción ---------------------------------------------------------
    def _crear_vista(self, vista_3d: bool) -> None:
        self.plotter = None
        if vista_3d:
            from pyvistaqt import QtInteractor

            self.plotter = QtInteractor(self)
            self.plotter.set_background("white")
            self.setCentralWidget(self.plotter.interactor)
            # Un clic sin arrastrar selecciona o dibuja; arrastrar sigue girando la cámara.
            self._pos_presion = None
            self.plotter.iren.add_observer("LeftButtonPressEvent", self._al_presionar)
            self.plotter.iren.add_observer("LeftButtonReleaseEvent", self._al_soltar)
        else:
            self.setCentralWidget(QLabel("Vista 3D desactivada"))

    def _crear_paneles(self) -> None:
        panel = QWidget()
        capa = QVBoxLayout(panel)
        self.selector_tabla = QComboBox()
        self.selector_tabla.currentTextChanged.connect(self._mostrar_tabla_elegida)
        self.titulo_tabla = QLabel()
        self.titulo_tabla.setWordWrap(True)
        self.tabla = QTableWidget()
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        capa.addWidget(self.selector_tabla)
        capa.addWidget(self.titulo_tabla)
        capa.addWidget(self.tabla)
        dock = QDockWidget("Resultados", self)
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        dock_reg = QDockWidget("Registro", self)
        dock_reg.setWidget(self.registro)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock_reg)
        self.resizeDocks([dock], [480], Qt.Horizontal)
        self.resizeDocks([dock_reg], [110], Qt.Vertical)

    def _crear_acciones(self) -> None:
        menu_archivo = self.menuBar().addMenu("&Archivo")
        self.accion_nuevo = QAction("Nuevo…", self, shortcut=QKeySequence.New, triggered=self._dialogo_nuevo)
        menu_archivo.addAction(self.accion_nuevo)
        self.accion_abrir = QAction("Abrir modelo…", self, shortcut=QKeySequence.Open, triggered=self._dialogo_abrir)
        self.accion_guardar = QAction("Guardar", self, shortcut=QKeySequence.Save, triggered=self._guardar)
        self.accion_guardar_como = QAction("Guardar como…", self, triggered=self._dialogo_guardar_como)
        self.accion_script = QAction("Exportar script OpenSeesPy…", self, triggered=self._dialogo_script)
        salir = QAction("Salir", self, shortcut=QKeySequence.Quit, triggered=self.close)
        for a in (self.accion_abrir, self.accion_guardar, self.accion_guardar_como, self.accion_script):
            menu_archivo.addAction(a)
        menu_archivo.addSeparator()
        menu_archivo.addAction(salir)

        menu_analisis = self.menuBar().addMenu("A&nálisis")
        self.accion_estatico = QAction("Estático lineal", self, shortcut="F5", triggered=self.ejecutar_estatico)
        self.accion_modal = QAction("Modal", self, shortcut="F6", triggered=self.ejecutar_modal)
        self.accion_esp_x = QAction("Espectral en X", self, triggered=lambda: self.ejecutar_espectral("X"))
        self.accion_esp_y = QAction("Espectral en Y", self, triggered=lambda: self.ejecutar_espectral("Y"))
        self._acciones_analisis = [self.accion_estatico, self.accion_modal, self.accion_esp_x, self.accion_esp_y]
        for a in self._acciones_analisis:
            menu_analisis.addAction(a)

        menu_diseno = self.menuBar().addMenu("D&iseño")
        self.accion_mamposteria = QAction("Revisar muros de mampostería (NTC)", self, shortcut="F8",
                                          triggered=self.ejecutar_mamposteria)
        menu_diseno.addAction(self.accion_mamposteria)

        barra = QToolBar("Principal", self)
        self.addToolBar(barra)
        barra.addAction(self.accion_nuevo)
        barra.addAction(self.accion_abrir)
        barra.addAction(self.accion_guardar)
        barra.addSeparator()
        barra.addWidget(QLabel(" Motor: "))
        self.selector_motor = QComboBox()
        self.selector_motor.addItems(MOTORES)
        self.selector_motor.currentTextChanged.connect(self._cambiar_motor)
        barra.addWidget(self.selector_motor)
        barra.addWidget(QLabel(" Modos: "))
        self.n_modos = QDoubleSpinBox(decimals=0, minimum=1, maximum=200, value=12)
        barra.addWidget(self.n_modos)
        for a in self._acciones_analisis:
            barra.addAction(a)
        barra.addSeparator()
        barra.addWidget(QLabel(" Ver: "))
        self.selector_vista = QComboBox()
        self.selector_vista.setMinimumWidth(180)
        self.selector_vista.currentTextChanged.connect(lambda _: self.actualizar_vista())
        barra.addWidget(self.selector_vista)
        barra.addWidget(QLabel(" Escala ×"))
        self.factor_escala = QDoubleSpinBox(decimals=1, minimum=0.0, maximum=1000.0, value=1.0, singleStep=0.5)
        self.factor_escala.setToolTip("Multiplica la escala automática de la deformada")
        self.factor_escala.valueChanged.connect(lambda _: self.actualizar_vista())
        barra.addWidget(self.factor_escala)

        self._crear_acciones_edicion()

    # --- archivo ----------------------------------------------------------------
    def abrir(self, ruta: str) -> None:
        try:
            self.sesion.abrir(ruta)
        except Exception as e:  # noqa: BLE001
            self._error(f"No se pudo abrir {ruta}:\n{e}")
            return
        self.log(f"Abierto {ruta}")
        self._actualizar_estado()
        self.actualizar_vista(reiniciar_camara=True)

    def _confirmar_descartar(self) -> bool:
        """True si se puede seguir sin guardar (no hay cambios o el usuario lo decide)."""
        if self.sincrono or self.sesion.modelo is None or not self.sesion.modificado:
            return True
        r = QMessageBox.question(
            self, "estruc_mx", "El modelo tiene cambios sin guardar. ¿Guardarlos?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if r == QMessageBox.Save:
            self._guardar()
            return not self.sesion.modificado
        return r == QMessageBox.Discard

    def closeEvent(self, evento) -> None:  # noqa: N802 - nombre de Qt
        if self._confirmar_descartar():
            evento.accept()
        else:
            evento.ignore()

    def _dialogo_abrir(self) -> None:
        if not self._confirmar_descartar():
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", "Modelos (*.json)")
        if ruta:
            self.abrir(ruta)

    def _guardar(self) -> None:
        if not self.sesion.ruta:
            return self._dialogo_guardar_como()
        self.sesion.guardar()
        self.log(f"Guardado {self.sesion.ruta}")
        self._actualizar_estado()

    def _dialogo_guardar_como(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar modelo", "", "Modelos (*.json)")
        if ruta:
            if not ruta.lower().endswith(".json"):
                ruta += ".json"
            self.sesion.guardar(ruta)
            self.log(f"Guardado {ruta}")
            self._actualizar_estado()

    def _dialogo_script(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar script", "modelo_opensees.py", "Python (*.py)")
        if ruta:
            self.sesion.exportar_script(ruta)
            self.log(f"Script OpenSeesPy exportado a {ruta}")

    # --- análisis ---------------------------------------------------------------
    def _cambiar_motor(self, motor: str) -> None:
        self.sesion.motor = motor
        self.sesion.limpiar_resultados()
        self.log(f"Motor: {motor}. Resultados anteriores descartados.")
        self._actualizar_estado()
        self.actualizar_vista()

    def ejecutar_estatico(self) -> None:
        self._lanzar("Análisis estático", self.sesion.analizar_estatico, "Desplazamientos")

    def ejecutar_modal(self) -> None:
        n = int(self.n_modos.value())
        self._lanzar(f"Análisis modal ({n} modos)", lambda: self.sesion.analizar_modal(n), "Modos")

    def ejecutar_espectral(self, direccion: str) -> None:
        n = int(self.n_modos.value())
        self._lanzar(
            f"Análisis espectral en {direccion}",
            lambda: self.sesion.analizar_espectral(direccion, "CQC", n),
            f"Derivas {direccion}",
        )

    def ejecutar_mamposteria(self) -> None:
        n = int(self.n_modos.value())

        def correr():
            r = self.sesion.revisar_mamposteria(n)
            for aviso in r.avisos:
                self._avisos_pendientes.append(aviso)
            return r

        self._avisos_pendientes = []
        self._lanzar("Revisión de mampostería", correr, _TABLAS_MAMPOSTERIA[0], vista=_VISTA_MAMPOSTERIA)

    def _lanzar(self, nombre: str, funcion: Callable[[], object], tabla_al_terminar: str, vista: str | None = None) -> None:
        if self.sesion.modelo is None or self._ocupado:
            return
        self._ocupado = True
        self._actualizar_estado()
        self.log(f"{nombre} con {self.sesion.motor}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def fin(_resultado) -> None:
            QApplication.restoreOverrideCursor()
            self._ocupado = False
            self.log(f"{nombre}: terminado")
            for aviso in getattr(self, "_avisos_pendientes", []):
                self.log(f"  Aviso: {aviso}")
            self._avisos_pendientes = []
            self._actualizar_estado()
            if vista:
                self.selector_vista.setCurrentText(vista)
            self.selector_tabla.setCurrentText(tabla_al_terminar)
            self._mostrar_tabla_elegida(tabla_al_terminar)
            self.actualizar_vista()

        def fallo(mensaje: str) -> None:
            QApplication.restoreOverrideCursor()
            self._ocupado = False
            self._actualizar_estado()
            self._error(f"{nombre} falló:\n{mensaje}")

        if self.sincrono:
            try:
                fin(funcion())
            except Exception as e:  # noqa: BLE001
                fallo(str(e))
            return
        tarea = _Tarea(funcion)
        tarea.senales.terminado.connect(fin)
        tarea.senales.error.connect(fallo)
        QThreadPool.globalInstance().start(tarea)

    # --- tablas -----------------------------------------------------------------
    def _tablas_disponibles(self) -> list[str]:
        s = self.sesion
        nombres = []
        if s.modelo is not None:
            nombres.append("Modelo")
            if s.modelo.diafragmas:
                nombres.append("Diafragmas")
        hay_muros = s.modelo is not None and any(a.tipo == "muro" for a in s.modelo.areas)
        hay_losas = s.modelo is not None and any(a.tipo == "losa" for a in s.modelo.areas)
        if s.estatico is not None:
            nombres += ["Desplazamientos", "Reacciones"]
            nombres += ["Fuerzas en muros"] * hay_muros + ["Momentos en losas"] * hay_losas
        if s.propiedades is not None:
            nombres.append("Modos")
        for d in sorted(s.espectrales):
            nombres.append(f"Derivas {d}")
            if hay_muros:
                nombres.append(f"Muros espectral {d}")
        if s.mamposteria is not None:
            nombres += list(_TABLAS_MAMPOSTERIA)
        return nombres

    def _combinacion_actual(self) -> str | None:
        texto = self.selector_vista.currentText()
        if self.sesion.estatico and texto in self.sesion.estatico.desplazamientos:
            return texto
        return self.sesion.estatico.combinaciones[0] if self.sesion.estatico else None

    def tabla_actual(self, nombre: str) -> Tabla | None:
        s = self.sesion
        if nombre == "Modelo" and s.modelo is not None:
            return s.resumen()
        if nombre == "Diafragmas" and s.modelo is not None:
            return s.tabla_diafragmas()
        if nombre in ("Desplazamientos", "Reacciones", "Fuerzas en muros", "Momentos en losas") and s.estatico is not None:
            combo = self._combinacion_actual()
            return {
                "Desplazamientos": s.tabla_desplazamientos, "Reacciones": s.tabla_reacciones,
                "Fuerzas en muros": s.tabla_muros, "Momentos en losas": s.tabla_losas,
            }[nombre](combo)
        if nombre == "Modos" and s.propiedades is not None:
            return s.tabla_modal()
        if nombre.startswith("Derivas ") and nombre[-1] in s.espectrales:
            return s.tabla_derivas(nombre[-1])
        if nombre.startswith("Muros espectral ") and nombre[-1] in s.espectrales:
            return s.tabla_muros_espectral(nombre[-1])
        if nombre in _TABLAS_MAMPOSTERIA and s.mamposteria is not None:
            return {
                _TABLAS_MAMPOSTERIA[0]: s.tabla_mamposteria, _TABLAS_MAMPOSTERIA[1]: s.tabla_mamposteria_detalle,
                _TABLAS_MAMPOSTERIA[2]: s.tabla_mamposteria_entrepisos,
            }[nombre]()
        return None

    def _mostrar_tabla_elegida(self, nombre: str) -> None:
        t = self.tabla_actual(nombre)
        self.tabla.clear()
        if t is None:
            self.titulo_tabla.setText("")
            self.tabla.setRowCount(0)
            self.tabla.setColumnCount(0)
            return
        self.titulo_tabla.setText(t.titulo)
        self.tabla.setColumnCount(len(t.columnas))
        self.tabla.setHorizontalHeaderLabels(t.columnas)
        self.tabla.setRowCount(len(t.filas))
        for i, fila in enumerate(t.filas):
            color = _COLOR_ESTADO.get(t.estados[i]) if i < len(t.estados) else None
            for j, valor in enumerate(fila):
                item = QTableWidgetItem(str(valor))
                if isinstance(valor, (int, float)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if color:
                    item.setBackground(QColor(color))
                self.tabla.setItem(i, j, item)
        self.tabla.resizeColumnsToContents()

    # --- vista 3D ---------------------------------------------------------------
    def _opciones_vista(self) -> list[str]:
        s = self.sesion
        opciones = [_VISTA_MODELO]
        if s.modelo is not None:
            opciones += [f"{_PREFIJO_CARGAS}{p.nombre}" for p in s.modelo.patrones]
        if s.estatico is not None:
            opciones += s.estatico.combinaciones
        if s.modos is not None:
            opciones += [f"Modo {i + 1} (T = {T:.3f} s)" for i, T in enumerate(s.modos.periodos)]
        if s.mamposteria is not None:
            opciones.append(_VISTA_MAMPOSTERIA)
        return opciones

    def tabla_de_vista(self, opcion: str) -> dict[str, list[float]] | None:
        """Desplazamientos que corresponden a la opción elegida en «Ver»."""
        s = self.sesion
        if s.estatico is not None and opcion in s.estatico.desplazamientos:
            return s.estatico.desplazamientos[opcion]
        if s.modos is not None and opcion.startswith("Modo "):
            i = int(opcion.split()[1]) - 1
            if i < len(s.modos.formas):
                return s.modos.formas[i]
        return None

    def actualizar_vista(self, reiniciar_camara: bool = False) -> None:
        if self.plotter is None:
            return
        if self.sesion.modelo is None:
            self.plotter.clear()
            self.plotter.render()
            return
        import pyvista as pv

        from ..visual.vista3d import COLORES_AREA, escala_para_tabla, malla_areas, malla_deformada, malla_rejilla

        modelo = self.sesion.modelo
        opcion = self.selector_vista.currentText() or _VISTA_MODELO
        tabla = self.tabla_de_vista(opcion)
        camara = None if reiniciar_camara or not self.plotter.renderer.actors else self.plotter.camera_position
        self.plotter.clear()
        if modelo.rejilla is not None:
            lineas, etiquetas = malla_rejilla(modelo.rejilla)
            if lineas is not None:
                self.plotter.add_mesh(lineas, color="#9bb7d4", line_width=1, pickable=False)
                self.plotter.add_point_labels(
                    etiquetas, etiquetas["nombre"], font_size=11, text_color="#3a6ea5", shape_opacity=0.0,
                    show_points=False, always_visible=True, pickable=False,
                )
            if self.modo != "seleccionar":
                pts = np.array([p for _, p in modelo.rejilla.intersecciones()], dtype=float)
                if len(pts):
                    self.plotter.add_mesh(pv.PolyData(pts), color="#5d8fc9", point_size=8, render_points_as_spheres=True, pickable=False)
        if modelo.barras:
            for tipo, color in (("columna", "#1f5fa8"), ("viga", "#2f7d32"), ("contraviento", "#8e44ad"), ("barra", "#555555")):
                sub = [b for b in modelo.barras if b.tipo == tipo]
                if sub:
                    self.plotter.add_mesh(
                        _malla_lineas(modelo, sub), color=color, line_width=3, opacity=0.35 if tabla else 1.0, pickable=False
                    )
        if modelo.nodos:
            self.plotter.add_mesh(
                pv.PolyData(np.array([n.coords for n in modelo.nodos])), color="black", point_size=7,
                render_points_as_spheres=True, pickable=False,
            )
        revisados = {}
        if opcion == _VISTA_MAMPOSTERIA and self.sesion.mamposteria is not None:
            revisados = {w.muro: w for w in self.sesion.mamposteria.muros}
            sub = [a for a in modelo.areas if a.id in revisados]
            if sub:
                caras = malla_areas(modelo, sub)
                caras.cell_data["D/C"] = [min(revisados[a.id].relacion, 2.0) if revisados[a.id].cumple
                                          else max(revisados[a.id].relacion, 1.01) for a in sub]
                self.plotter.add_mesh(
                    caras, scalars="D/C", cmap="RdYlGn_r", clim=[0, 1.2], show_edges=True, edge_color="#555555", pickable=False,
                    scalar_bar_args={"title": "D/C (rojo: no cumple)"},
                )
                c = np.array([modelo.esquinas(a).mean(axis=0) for a in sub])
                etiquetas = [f"{a.id}\n{revisados[a.id].relacion:.2f}" + ("" if revisados[a.id].cumple else "\nno cumple")
                             for a in sub]
                self.plotter.add_point_labels(c, etiquetas, font_size=10, shape_opacity=0.3, show_points=False,
                                              always_visible=True, pickable=False)
        for tipo, color in COLORES_AREA.items():
            sub = [a for a in modelo.areas if a.tipo == tipo and a.id not in revisados]
            if sub:
                self.plotter.add_mesh(
                    malla_areas(modelo, sub), color=color, opacity=0.12 if tabla else 0.45, show_edges=True,
                    edge_color="#7a6a55", pickable=False,
                )
        apoyados = {a.nodo for a in modelo.apoyos}
        if apoyados:
            pts = np.array([n.coords for n in modelo.nodos if n.id in apoyados])
            self.plotter.add_mesh(pv.PolyData(pts), color="#e67e22", point_size=14, render_points_as_spheres=False, pickable=False)
        if tabla is not None and (modelo.barras or modelo.areas):
            escala = escala_para_tabla(modelo, tabla) * self.factor_escala.value()
            lineas, cuads = malla_deformada(modelo, tabla, escala, self._malla())
            barra = {"title": "Desplazamiento" + (" (m)" if not opcion.startswith("Modo") else " (relativo)")}
            if cuads is not None:
                self.plotter.add_mesh(cuads, scalars="desplazamiento", cmap="viridis", show_edges=True, opacity=0.9,
                                      scalar_bar_args=barra, pickable=False)
            if lineas is not None:
                self.plotter.add_mesh(lineas, scalars="desplazamiento", line_width=4, cmap="viridis",
                                      scalar_bar_args=barra, pickable=False)
        if tabla is None:
            self._dibujar_diafragmas()
        titulo = f"{modelo.nombre} - {opcion}"
        if opcion.startswith(_PREFIJO_CARGAS):
            titulo += self._dibujar_cargas(opcion.removeprefix(_PREFIJO_CARGAS))
        self.plotter.add_text(titulo, font_size=9, color="black", name="titulo")
        self.plotter.show_axes()
        self._dibujar_seleccion(render=False)
        if camara is None:
            self.plotter.view_isometric()
        else:
            self.plotter.camera_position = camara
        self.plotter.render()

    def _dibujar_cargas(self, patron: str) -> str:
        """Flechas de las cargas del patrón; devuelve una nota para el título."""
        from ..visual.vista3d import COLORES_CARGA, flechas_cargas, malla_flechas

        m = self.sesion.modelo
        nota = ""
        for clave, fl in flechas_cargas(m, patron).items():
            malla = malla_flechas(fl)
            if malla is None:
                continue
            self.plotter.add_mesh(malla, color=COLORES_CARGA[clave], pickable=False)
            if fl.textos:
                self.plotter.add_point_labels(
                    fl.posiciones, fl.textos, font_size=10, text_color=COLORES_CARGA[clave], shape_opacity=0.0,
                    show_points=False, always_visible=True, pickable=False,
                )
        p = next((p for p in m.patrones if p.nombre == patron), None)
        if p is not None and p.peso_propio:
            nota = f" (más {p.peso_propio:g} × peso propio)"
        return nota

    def _dibujar_diafragmas(self) -> None:
        """Centro de masa de cada diafragma rígido, con su nombre."""
        import pyvista as pv

        diafragmas = self._malla().diafragmas
        if not diafragmas:
            return
        pts = np.array([d.centro for d in diafragmas], dtype=float)
        self.plotter.add_mesh(pv.PolyData(pts), color="#7d3c98", point_size=15, render_points_as_spheres=True, pickable=False)
        self.plotter.add_point_labels(
            pts, [f"CM {d.nombre}" for d in diafragmas], font_size=10, text_color="#7d3c98", shape_opacity=0.0,
            show_points=False, always_visible=True, pickable=False,
        )

    def _malla(self):
        """Malla de análisis del modelo actual (se recalcula solo si el modelo cambió)."""
        from ..modelo.malla import discretizar

        m = self.sesion.modelo
        if getattr(self, "_malla_de", None) is not m:
            self._malla_cache = discretizar(m)
            self._malla_de = m
        return self._malla_cache

    def _dibujar_seleccion(self, render: bool = True) -> None:
        """Resalta lo seleccionado (y el primer extremo de una barra en dibujo) sin redibujar todo."""
        if self.plotter is None:
            return
        import pyvista as pv

        for nombre in ("sel_barras", "sel_nodos", "sel_areas", "primer_punto"):
            self.plotter.remove_actor(nombre, render=False)
        m = self.sesion.modelo
        # Sobre una deformada el resaltado estorba: solo se dibuja en el modelo sin deformar
        if m is not None and self.tabla_de_vista(self.selector_vista.currentText()) is None:
            areas = [a for a in m.areas if a.id in self.sel_areas]
            if areas:
                from ..visual.vista3d import malla_areas

                self.plotter.add_mesh(malla_areas(m, areas), color="red", opacity=0.45, show_edges=True, edge_color="red",
                                      line_width=3, name="sel_areas", pickable=False)
            barras = [b for b in m.barras if b.id in self.sel_barras]
            if barras:
                self.plotter.add_mesh(_malla_lineas(m, barras), color="red", line_width=6, name="sel_barras", pickable=False)
            nodos = [n.coords for n in m.nodos if n.id in self.sel_nodos]
            if nodos:
                self.plotter.add_mesh(pv.PolyData(np.array(nodos)), color="red", point_size=13, render_points_as_spheres=True, name="sel_nodos", pickable=False)
            if self.primer_punto is not None:
                p = np.array([self._coords(self.primer_punto)])
                self.plotter.add_mesh(pv.PolyData(p), color="#f39c12", point_size=16, render_points_as_spheres=True, name="primer_punto", pickable=False)
        if render:
            self.plotter.render()

    # --- ratón en la vista 3D ---------------------------------------------------
    def _al_presionar(self, *_args) -> None:
        self._pos_presion = self.plotter.iren.get_event_position()

    def _al_soltar(self, *_args) -> None:
        if self._pos_presion is None:
            return
        x, y = self.plotter.iren.get_event_position()
        x0, y0 = self._pos_presion
        self._pos_presion = None
        if abs(x - x0) > 3 or abs(y - y0) > 3:
            return  # fue un arrastre para girar la vista
        i = self.plotter.iren.interactor
        self.clic(self.objetivo_en_pantalla(x, y), aditivo=bool(i.GetShiftKey() or i.GetControlKey()))

    def objetivo_en_pantalla(self, x: float, y: float):
        """Qué hay bajo el punto (x, y) de la pantalla, en el formato de `clic`."""
        from ..visual.seleccion import elegir, matriz_camara

        m = self.sesion.modelo
        if m is None or self.plotter is None:
            return None
        ren = self.plotter.renderer
        ancho, alto = ren.GetSize()
        nodos = np.array([n.coords for n in m.nodos]).reshape(-1, 3)
        indice = {n.id: n.coords for n in m.nodos}
        barras = np.array([[indice[b.i], indice[b.j]] for b in m.barras]).reshape(-1, 2, 3)
        puntos = []
        if self.modo != "seleccionar" and m.rejilla is not None:
            puntos = [p for _, p in m.rejilla.intersecciones()]
        # Al dibujar, los muros y losas no estorban: solo cuentan nodos y puntos de la rejilla
        areas = None
        if self.modo == "seleccionar" and m.areas:
            areas = np.array([[indice[n] for n in a.nodos] for a in m.areas]).reshape(-1, 4, 3)
        r = elegir((x, y), nodos, barras, np.array(puntos, dtype=float).reshape(-1, 3), matriz_camara(ren), ancho, alto, areas)
        if r is None:
            return None
        que, k = r
        if que == "nodo":
            return "nodo", m.nodos[k].id
        if que == "barra":
            return "barra", m.barras[k].id
        if que == "area":
            return "area", m.areas[k].id
        return "punto", tuple(puntos[k])

    # --- estado -----------------------------------------------------------------
    def _actualizar_estado(self) -> None:
        hay = self.sesion.modelo is not None
        self._actualizar_estado_edicion()
        for a in (self.accion_guardar, self.accion_guardar_como, self.accion_script):
            a.setEnabled(hay)
        for a in self._acciones_analisis:
            a.setEnabled(hay and not self._ocupado)
        self.accion_mamposteria.setEnabled(hay and not self._ocupado)
        hay_espectro = hay and self.sesion.modelo.espectro is not None
        self.accion_esp_x.setEnabled(hay_espectro and not self._ocupado)
        self.accion_esp_y.setEnabled(hay_espectro and not self._ocupado)

        for selector, opciones in ((self.selector_tabla, self._tablas_disponibles()), (self.selector_vista, self._opciones_vista())):
            actual = selector.currentText()
            selector.blockSignals(True)
            selector.clear()
            selector.addItems(opciones)
            if actual in opciones:
                selector.setCurrentText(actual)
            selector.blockSignals(False)
        self._mostrar_tabla_elegida(self.selector_tabla.currentText())
        titulo = "estruc_mx"
        if hay:
            titulo += f" - {self.sesion.ruta or 'sin guardar'}" + (" *" if self.sesion.modificado else "")
        self.setWindowTitle(titulo)

    def log(self, texto: str) -> None:
        self.registro.appendPlainText(texto)

    def _error(self, texto: str) -> None:
        self.log(texto.splitlines()[0])
        if not self.sincrono:
            QMessageBox.critical(self, "estruc_mx", texto)


def _malla_lineas(modelo, barras):
    import pyvista as pv

    indice = {n.id: n.coords for n in modelo.nodos}
    puntos = np.array([p for b in barras for p in (indice[b.i], indice[b.j])], dtype=float)
    lineas = np.array([[2, 2 * k, 2 * k + 1] for k in range(len(barras))], dtype=np.int64).ravel()
    return pv.PolyData(puntos, lines=lineas)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    ventana = VentanaPrincipal()
    ventana.show()
    if len(argv) > 1:
        ventana.abrir(argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
