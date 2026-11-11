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


def test_crear_marco_desde_cero_calcular_y_guardar(ventana, tmp_path):
    ventana.nuevo_modelo("Nuevo", [6.0, 6.0], [5.0], [3.5, 3.0])
    m = ventana.sesion.modelo
    assert len(m.barras) == 26 and ventana.arbol.topLevelItem(1).text(0) == "Barras (26)"
    assert ventana.accion_deshacer.text() == "Deshacer marco desde rejilla"

    # Cargas de gravedad en todas las vigas y análisis
    vigas = [b.id for b in m.barras if b.tipo == "viga"]
    ventana.seleccionar(barras=vigas)
    ventana.hacer_carga_distribuida("CM", "Z", -15.0)
    ventana.ejecutar_estatico()
    assert ventana.selector_tabla.currentText() == "Desplazamientos"
    assert "1.3CM+1.5CV" in items(ventana.selector_vista)

    # Dibujar una barra con dos clics descarta los resultados
    ventana.fijar_modo("barra")
    ventana.clic(("punto", (0.0, 0.0, 3.5)))
    ventana.clic(("nodo", "C2-N2"))
    assert ventana.sesion.modelo.barra("D1").tipo == "contraviento"
    assert ventana.sesion.estatico is None and items(ventana.selector_tabla) == ["Modelo"]
    ventana.deshacer()
    assert "D1" not in {b.id for b in ventana.sesion.modelo.barras}

    # Selección y panel de propiedades
    ventana.fijar_modo("seleccionar")
    ventana.clic(("barra", "C1"))
    assert ventana.sel_barras == {"C1"} and "seccion" in ventana.controles_propiedades
    ventana.aplicar_propiedad("seccion", "V25x50")
    ventana.aplicar_propiedad("id", "C-A1")
    assert ventana.sesion.modelo.barra("C-A1").seccion == "V25x50" and ventana.sel_barras == {"C-A1"}
    ventana.clic(("nodo", "A1-Base"))
    ventana.aplicar_propiedad("apoyo", "Articulado")
    apoyos = {a.nodo: a.restricciones for a in ventana.sesion.modelo.apoyos}
    assert apoyos["A1-Base"] == (True, True, True, False, False, False)
    ventana.clic(None)
    assert not ventana.sel_nodos and not ventana.sel_barras

    # Definir: renombrar un patrón se propaga a cargas y combinaciones
    ventana.hacer_definir("patrones", [["Muerta", "muerta"], ["CV", "viva"]], {"CM": "Muerta"})
    assert ventana.sesion.modelo.cargas_distribuidas[0].patron == "Muerta"

    # Borrar con la selección
    ventana.seleccionar(nodos=["C1-N2"])
    ventana.borrar_seleccion()
    assert "C1-N2" not in {n.id for n in ventana.sesion.modelo.nodos}

    # Guardar y reabrir
    ruta = tmp_path / "nuevo.json"
    ventana.sesion.guardar(str(ruta))
    assert not ventana.sesion.modificado
    ventana.abrir(str(ruta))
    assert len(ventana.sesion.modelo.barras) == 23 and ventana.sesion.modelo.rejilla is not None
    ventana.ejecutar_estatico()
    assert ventana.sesion.estatico is not None


def test_errores_de_edicion_se_registran_sin_cambiar_el_modelo(ventana):
    ventana.nuevo_modelo("Nuevo", [6.0], [5.0], [3.0])
    antes = ventana.sesion.modelo
    ventana.seleccionar(barras=["C1"])
    ventana.aplicar_propiedad("rotacion", "abc")
    assert "No se pudo cambiar" in ventana.registro.toPlainText()
    ventana.fijar_modo("columna")
    ventana.clic(("punto", (0.0, 0.0, 0.0)))  # no hay nivel abajo de la base
    assert ventana.sesion.modelo is antes
