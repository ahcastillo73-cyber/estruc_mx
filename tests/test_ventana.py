"""Prueba de la ventana sin vista 3D (no necesita OpenGL) y con análisis síncronos."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 no está instalado")
pytest.importorskip("pytestqt", reason="pytest-qt no está instalado")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from estruc_mx.app.ventana import VentanaPrincipal  # noqa: E402
from estruc_mx.modelo import EspectroNTC  # noqa: E402

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


def test_dibujar_muros_y_losas_analizar_y_ver_fuerzas(ventana):
    ventana.nuevo_modelo("Muros", [5.0], [4.0], [3.0, 3.0])
    ventana.selector_seccion_area.setCurrentText("Muro tabique 14")
    ventana.fijar_modo("muro")
    ventana.clic(("nodo", "A1-N1"))
    ventana.clic(("nodo", "B1-N1"))  # muro A1–B1 de la base al N1
    ventana.clic(("nodo", "B2-N1"))  # sigue desde B1: muro B1–B2
    m = ventana.sesion.modelo
    assert [a.id for a in m.areas] == ["M1", "M2"] and m.area("M1").seccion == "Muro tabique 14"
    ventana.fijar_modo("losa")
    ventana.selector_seccion_area.setCurrentText("Losa 10")
    ventana.clic(("punto", (0.0, 0.0, 3.0)))
    ventana.clic(("punto", (5.0, 4.0, 3.0)))
    assert ventana.sesion.modelo.area("L1").tipo == "losa"
    assert ventana.arbol.topLevelItem(2).text(0) == "Muros y losas (3)"

    # Seleccionar la losa, cargarla y ver sus propiedades
    ventana.fijar_modo("seleccionar")
    ventana.clic(("area", "L1"))
    assert ventana.sel_areas == {"L1"} and "seccion_area" in ventana.controles_propiedades
    ventana.hacer_carga_area("CM", "Z", -5.0)
    assert ventana.sesion.modelo.cargas_area[0].area == "L1"
    ventana.aplicar_propiedad("id", "Azotea")
    assert ventana.sel_areas == {"Azotea"} and ventana.sesion.modelo.cargas_area[0].area == "Azotea"

    ventana.ejecutar_estatico()
    assert {"Fuerzas en muros", "Momentos en losas"} <= set(items(ventana.selector_tabla))
    ventana.selector_tabla.setCurrentText("Fuerzas en muros")
    assert ventana.tabla.rowCount() == 2
    ventana.selector_tabla.setCurrentText("Momentos en losas")
    assert ventana.tabla.rowCount() == 1
    # Solo los nodos del modelo en la tabla de desplazamientos
    ventana.selector_tabla.setCurrentText("Desplazamientos")
    assert ventana.tabla.rowCount() == len(ventana.sesion.modelo.nodos)

    # Borrar un muro con la selección y deshacer
    ventana.seleccionar(areas=["M2"])
    ventana.borrar_seleccion()
    assert [a.id for a in ventana.sesion.modelo.areas] == ["M1", "Azotea"]
    ventana.deshacer()
    assert len(ventana.sesion.modelo.areas) == 3

    ventana.hacer_definir(
        "secciones_area",
        [["Tabique", "muro", "Tabique rojo", "0.14", "1"], ["Muro concreto 15", "muro", "Concreto f'c 250", "0.15", "0.5"],
         ["Losa 10", "losa", "Concreto f'c 250", "0.1", "1"]],
        {"Muro tabique 14": "Tabique"},
    )
    assert ventana.sesion.modelo.area("M1").seccion == "Tabique"
    assert ventana.sesion.modelo.seccion_area("Muro concreto 15").mod_rigidez == 0.5


def test_losas_desde_rejilla_y_espectral_con_muros(ventana):
    ventana.nuevo_modelo("Edificio", [6.0, 4.0], [5.0], [3.0])
    n = ventana.sesion.editor.losas_desde_rejilla("Losa 10")
    assert n == 2
    ventana.sesion.editor.agregar_muro((0, 0), (6, 0), 0.0, 3.0, "Muro concreto 15")
    ventana.sesion.editor.definir_espectro(EspectroNTC(nombre="E", a0=0.1, c=0.3, Ta=0.4, Tb=1.2, k=1.0))
    ventana.n_modos.setValue(4)
    ventana.ejecutar_espectral("X")
    assert "Muros espectral X" in items(ventana.selector_tabla)
    ventana.selector_tabla.setCurrentText("Muros espectral X")
    assert ventana.tabla.rowCount() == 1
