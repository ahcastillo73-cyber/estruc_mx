"""Diálogos de edición: formularios sencillos y tablas para «Definir»."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..modelo import EjeRejilla, Nivel, Rejilla
from .definiciones import Columna

_CLAVE_ORIGINAL = Qt.UserRole + 1


@dataclass
class Campo:
    clave: str
    etiqueta: str
    valor: object = ""
    opciones: list[str] = field(default_factory=list)  # combo si hay opciones
    ayuda: str = ""


class DialogoFormulario(QDialog):
    """Formulario a partir de una lista de campos. El tipo del valor inicial decide el control:
    bool -> casilla, float -> número, str con opciones -> lista, str -> texto."""

    def __init__(self, titulo: str, campos: list[Campo], parent=None, nota: str = ""):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.controles: dict[str, QWidget] = {}
        capa = QVBoxLayout(self)
        if nota:
            n = QLabel(nota)
            n.setWordWrap(True)
            capa.addWidget(n)
        form = QFormLayout()
        capa.addLayout(form)
        for c in campos:
            if isinstance(c.valor, bool):
                w = QCheckBox()
                w.setChecked(c.valor)
            elif isinstance(c.valor, (int, float)):
                w = QDoubleSpinBox(decimals=4, minimum=-1e12, maximum=1e12)
                w.setValue(float(c.valor))
            elif c.opciones:
                w = QComboBox()
                w.addItems(c.opciones)
                if c.valor in c.opciones:
                    w.setCurrentText(str(c.valor))
            else:
                w = QLineEdit(str(c.valor))
            if c.ayuda:
                w.setToolTip(c.ayuda)
            form.addRow(c.etiqueta, w)
            self.controles[c.clave] = w
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)

    def valores(self) -> dict[str, object]:
        out = {}
        for k, w in self.controles.items():
            if isinstance(w, QCheckBox):
                out[k] = w.isChecked()
            elif isinstance(w, QDoubleSpinBox):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
            else:
                out[k] = w.text()
        return out

    def fijar(self, **valores) -> None:
        """Llena controles (útil en pruebas)."""
        for k, v in valores.items():
            w = self.controles[k]
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(v))
            elif isinstance(w, QComboBox):
                w.setCurrentText(str(v))
            else:
                w.setText(str(v))


class TablaEditable(QWidget):
    """Tabla con botones para agregar y quitar filas. Recuerda el nombre original de cada fila
    para propagar los renombres."""

    def __init__(self, columnas: list[Columna], filas: list[list[str]], parent=None):
        super().__init__(parent)
        self.columnas = columnas
        capa = QVBoxLayout(self)
        self.tabla = QTableWidget(0, len(columnas))
        self.tabla.setHorizontalHeaderLabels([c.titulo for c in columnas])
        self.tabla.verticalHeader().setVisible(False)
        capa.addWidget(self.tabla)
        fila_botones = QHBoxLayout()
        agregar = QPushButton("Agregar")
        agregar.clicked.connect(lambda: self.agregar_fila())
        quitar = QPushButton("Quitar")
        quitar.clicked.connect(self.quitar_seleccionadas)
        fila_botones.addWidget(agregar)
        fila_botones.addWidget(quitar)
        fila_botones.addStretch()
        capa.addLayout(fila_botones)
        for f in filas:
            self.agregar_fila(f, original=f[0])
        self.tabla.resizeColumnsToContents()

    def agregar_fila(self, valores: list[str] | None = None, original: str | None = None) -> None:
        r = self.tabla.rowCount()
        self.tabla.insertRow(r)
        if valores is None:
            if r > 0:  # copia la fila anterior, como punto de partida
                valores = self.fila(r - 1)
                valores[0] = f"{valores[0]} (copia)"
            else:
                valores = [c.opciones[0] if c.opciones else "" for c in self.columnas]
        for j, (c, v) in enumerate(zip(self.columnas, valores)):
            if c.opciones:
                combo = QComboBox()
                combo.addItems(c.opciones)
                combo.setCurrentText(v)
                self.tabla.setCellWidget(r, j, combo)
            else:
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(_CLAVE_ORIGINAL, original)
                self.tabla.setItem(r, j, item)

    def quitar_seleccionadas(self) -> None:
        for r in sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True):
            self.tabla.removeRow(r)

    def fila(self, r: int) -> list[str]:
        out = []
        for j in range(len(self.columnas)):
            w = self.tabla.cellWidget(r, j)
            if isinstance(w, QComboBox):
                out.append(w.currentText())
            else:
                it = self.tabla.item(r, j)
                out.append(it.text() if it else "")
        return out

    def filas(self) -> list[list[str]]:
        return [self.fila(r) for r in range(self.tabla.rowCount())]

    def renombres(self) -> dict[str, str]:
        out = {}
        for r in range(self.tabla.rowCount()):
            it = self.tabla.item(r, 0)
            original = it.data(_CLAVE_ORIGINAL) if it else None
            if original and it.text().strip() != original:
                out[original] = it.text().strip()
        return out


class DialogoTabla(QDialog):
    """Edita una colección completa; `validar(filas, renombres)` lanza ValueError si algo falla
    y el diálogo queda abierto mostrando el error."""

    def __init__(self, titulo: str, columnas: list[Columna], filas: list[list[str]], validar=None, parent=None, nota: str = ""):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(760, 380)
        self.validar = validar
        capa = QVBoxLayout(self)
        if nota:
            n = QLabel(nota)
            n.setWordWrap(True)
            capa.addWidget(n)
        self.editor = TablaEditable(columnas, filas)
        capa.addWidget(self.editor)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)

    def _aceptar(self) -> None:
        if self.validar is not None:
            try:
                self.validar(self.editor.filas(), self.editor.renombres())
            except ValueError as e:
                QMessageBox.warning(self, self.windowTitle(), str(e))
                return
        self.accept()


class DialogoRejilla(QDialog):
    """Ejes X, ejes Y y niveles en tres pestañas."""

    def __init__(self, rejilla: Rejilla | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rejilla: ejes y niveles")
        self.resize(460, 420)
        r = rejilla or Rejilla()
        capa = QVBoxLayout(self)
        pestanas = QTabWidget()
        self.tablas = {
            "ejes_x": TablaEditable([Columna("Nombre"), Columna("X (m)")], [[e.nombre, f"{e.coord:g}"] for e in r.ejes_x]),
            "ejes_y": TablaEditable([Columna("Nombre"), Columna("Y (m)")], [[e.nombre, f"{e.coord:g}"] for e in r.ejes_y]),
            "niveles": TablaEditable([Columna("Nombre"), Columna("Z (m)")], [[n.nombre, f"{n.z:g}"] for n in r.niveles]),
        }
        pestanas.addTab(self.tablas["ejes_x"], "Ejes X")
        pestanas.addTab(self.tablas["ejes_y"], "Ejes Y")
        pestanas.addTab(self.tablas["niveles"], "Niveles")
        capa.addWidget(pestanas)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)

    def rejilla(self) -> Rejilla:
        def leer(clave):
            out = []
            for nombre, valor in self.tablas[clave].filas():
                if nombre.strip():
                    out.append((nombre.strip(), float(valor.replace(",", "."))))
            return out

        return Rejilla(
            ejes_x=[EjeRejilla(nombre=n, coord=v) for n, v in leer("ejes_x")],
            ejes_y=[EjeRejilla(nombre=n, coord=v) for n, v in leer("ejes_y")],
            niveles=[Nivel(nombre=n, z=v) for n, v in leer("niveles")],
        )

    def _aceptar(self) -> None:
        try:
            self.rejilla()
        except ValueError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        self.accept()
