"""Ventana principal: modelo 3D en el centro, tablas a la derecha y registro abajo."""

from __future__ import annotations

import sys
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QKeySequence
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

from .sesion import MOTORES, Sesion, Tabla

_VISTA_MODELO = "Modelo sin deformar"


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


class VentanaPrincipal(QMainWindow):
    def __init__(self, vista_3d: bool = True, sincrono: bool = False):
        super().__init__()
        self.sesion = Sesion()
        self.sincrono = sincrono
        self._ocupado = False
        self.setWindowTitle("estruc_mx")
        self.resize(1400, 850)

        self._crear_vista(vista_3d)
        self._crear_paneles()
        self._crear_acciones()
        self._actualizar_estado()

    # --- construcción ---------------------------------------------------------
    def _crear_vista(self, vista_3d: bool) -> None:
        self.plotter = None
        if vista_3d:
            from pyvistaqt import QtInteractor

            self.plotter = QtInteractor(self)
            self.plotter.set_background("white")
            self.setCentralWidget(self.plotter.interactor)
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

        barra = QToolBar("Principal", self)
        self.addToolBar(barra)
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

    def _dialogo_abrir(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", "Modelos (*.json)")
        if ruta:
            self.abrir(ruta)

    def _guardar(self) -> None:
        if not self.sesion.ruta:
            return self._dialogo_guardar_como()
        self.sesion.guardar()
        self.log(f"Guardado {self.sesion.ruta}")

    def _dialogo_guardar_como(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar modelo", "", "Modelos (*.json)")
        if ruta:
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

    def _lanzar(self, nombre: str, funcion: Callable[[], object], tabla_al_terminar: str) -> None:
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
            self._actualizar_estado()
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
        if s.estatico is not None:
            nombres += ["Desplazamientos", "Reacciones"]
        if s.propiedades is not None:
            nombres.append("Modos")
        nombres += [f"Derivas {d}" for d in sorted(s.espectrales)]
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
        if nombre in ("Desplazamientos", "Reacciones") and s.estatico is not None:
            combo = self._combinacion_actual()
            return s.tabla_desplazamientos(combo) if nombre == "Desplazamientos" else s.tabla_reacciones(combo)
        if nombre == "Modos" and s.propiedades is not None:
            return s.tabla_modal()
        if nombre.startswith("Derivas ") and nombre[-1] in s.espectrales:
            return s.tabla_derivas(nombre[-1])
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
            for j, valor in enumerate(fila):
                item = QTableWidgetItem(str(valor))
                if isinstance(valor, (int, float)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(i, j, item)
        self.tabla.resizeColumnsToContents()

    # --- vista 3D ---------------------------------------------------------------
    def _opciones_vista(self) -> list[str]:
        s = self.sesion
        opciones = [_VISTA_MODELO]
        if s.estatico is not None:
            opciones += s.estatico.combinaciones
        if s.modos is not None:
            opciones += [f"Modo {i + 1} (T = {T:.3f} s)" for i, T in enumerate(s.modos.periodos)]
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
        if self.plotter is None or self.sesion.modelo is None:
            return
        from ..visual.vista3d import escala_para_tabla, malla_desde_tabla

        modelo = self.sesion.modelo
        opcion = self.selector_vista.currentText() or _VISTA_MODELO
        tabla = self.tabla_de_vista(opcion)
        camara = None if reiniciar_camara else self.plotter.camera_position
        self.plotter.clear()
        self.plotter.add_mesh(malla_desde_tabla(modelo, None), color="gray", line_width=2, opacity=0.35 if tabla else 1.0)
        if tabla is not None:
            escala = escala_para_tabla(modelo, tabla) * self.factor_escala.value()
            self.plotter.add_mesh(
                malla_desde_tabla(modelo, tabla, escala), scalars="desplazamiento", line_width=4, cmap="viridis",
                scalar_bar_args={"title": "Desplazamiento" + (" (m)" if not opcion.startswith("Modo") else " (relativo)")},
            )
        self.plotter.add_text(f"{modelo.nombre} - {opcion}", font_size=9, color="black")
        self.plotter.show_axes()
        if camara is None:
            self.plotter.view_isometric()
        else:
            self.plotter.camera_position = camara
        self.plotter.render()

    # --- estado -----------------------------------------------------------------
    def _actualizar_estado(self) -> None:
        hay = self.sesion.modelo is not None
        for a in (self.accion_guardar, self.accion_guardar_como, self.accion_script):
            a.setEnabled(hay)
        for a in self._acciones_analisis:
            a.setEnabled(hay and not self._ocupado)
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
        if self.sesion.ruta:
            titulo += f" - {self.sesion.ruta}"
        self.setWindowTitle(titulo)

    def log(self, texto: str) -> None:
        self.registro.appendPlainText(texto)

    def _error(self, texto: str) -> None:
        self.log(texto.splitlines()[0])
        if not self.sincrono:
            QMessageBox.critical(self, "estruc_mx", texto)


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
