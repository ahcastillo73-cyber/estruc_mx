"""Prueba de la ventana sin vista 3D (no necesita OpenGL) y con análisis síncronos."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 no está instalado")
pytest.importorskip("pytestqt", reason="pytest-qt no está instalado")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from estruc_mx.app.ventana import VentanaPrincipal  # noqa: E402

EJEMPLO = str(Path(__file__).resolve().parent.parent / "ejemplos" / "marco_3niveles.json")


@pytest.fixture
def ventana(qtbot):
    v = VentanaPrincipal(vista_3d=False, sincrono=True)
    qtbot.addWidget(v)
    return v


def items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_sin_modelo_no_se_puede_analizar(ventana):
    assert not ventana.accion_estatico.isEnabled()
    assert items(ventana.selector_tabla) == []


def test_abrir_y_analizar_llena_tablas_y_vistas(ventana):
    ventana.abrir(EJEMPLO)
    assert ventana.accion_estatico.isEnabled() and ventana.accion_esp_x.isEnabled()
    assert ventana.tabla.rowCount() > 0  # resumen del modelo

    ventana.ejecutar_estatico()
    assert ventana.selector_tabla.currentText() == "Desplazamientos"
    assert ventana.tabla.rowCount() == 24
    assert "1.1CM+SX" in items(ventana.selector_vista)
    assert ventana.tabla_de_vista("1.1CM+SX") is not None

    ventana.n_modos.setValue(6)
    ventana.ejecutar_espectral("Y")
    assert ventana.selector_tabla.currentText() == "Derivas Y"
    assert ventana.tabla.rowCount() == 3
    modos = [t for t in items(ventana.selector_vista) if t.startswith("Modo ")]
    assert len(modos) == 6 and ventana.tabla_de_vista(modos[0]) is not None


def test_cambiar_de_motor_descarta_resultados(ventana):
    ventana.abrir(EJEMPLO)
    ventana.ejecutar_estatico()
    ventana.selector_motor.setCurrentText("opensees")
    assert ventana.sesion.estatico is None
    assert items(ventana.selector_tabla) == ["Modelo"]


def test_error_al_abrir_se_registra(ventana, tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text("{}", encoding="utf-8")
    ventana.abrir(str(malo))
    assert "No se pudo abrir" in ventana.registro.toPlainText()
    assert ventana.sesion.modelo is None
