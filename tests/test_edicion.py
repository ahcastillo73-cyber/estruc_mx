"""Edición del modelo sin interfaz gráfica: editor con deshacer, tablas de Definir y selección."""

import json

import numpy as np
import pytest

from estruc_mx.app import definiciones as dfn
from estruc_mx.modelo import Edificio, Editor, Rejilla
from estruc_mx.motores import pynite
from estruc_mx.visual.seleccion import elegir


@pytest.fixture
def editor():
    e = Editor()
    e.nuevo("Prueba", Rejilla.regular([6.0, 6.0], [5.0], [3.5, 3.0]))
    return e


def test_rejilla_regular_nombra_ejes_como_etabs():
    r = Rejilla.regular([6, 6], [5, 5], [3.5])
    assert [e.nombre for e in r.ejes_x] == ["A", "B", "C"]
    assert [e.coord for e in r.ejes_y] == [0, 5, 10]
    assert [n.nombre for n in r.niveles] == ["Base", "N1"]
    assert ("B2-N1", (6.0, 5.0, 3.5)) in r.intersecciones()


def test_marco_desde_rejilla_y_analisis(editor):
    n = editor.marco_desde_rejilla("C40x40", "V25x50")
    m = editor.modelo
    # 6 columnas y 7 vigas por nivel, 2 niveles
    assert n == 26 and len(m.nodos) == 18 and len(m.apoyos) == 6
    assert m.nodo("B1-N1").coords.tolist() == [6.0, 0.0, 3.5]
    assert {b.tipo for b in m.barras} == {"columna", "viga"}
    # Repetirlo no duplica nada
    assert editor.marco_desde_rejilla("C40x40", "V25x50") == 0

    vigas = [b.id for b in m.barras if b.tipo == "viga"]
    editor.asignar_carga_distribuida(vigas, "CM", "Z", -20.0)
    r = pynite.analizar(editor.modelo)
    longitud = sum(editor.modelo.longitud(editor.modelo.barra(v)) for v in vigas)
    assert sum(v[2] for v in r.reacciones["CM+CV"].values()) == pytest.approx(20.0 * longitud)


def test_deshacer_y_rehacer(editor):
    editor.marco_desde_rejilla("C40x40", "V25x50")
    assert not editor.puede_rehacer
    editor.borrar(nodos=["A1-N2"])
    assert len(editor.modelo.barras) == 23  # se lleva su columna y dos vigas
    assert editor.texto_deshacer == "Borrar 1 objeto"
    editor.deshacer()
    assert len(editor.modelo.barras) == 26 and editor.puede_rehacer
    editor.rehacer()
    assert len(editor.modelo.barras) == 23
    editor.deshacer()
    editor.deshacer()
    assert editor.modelo.barras == []
    # Un cambio nuevo borra lo que se podía rehacer
    editor.agregar_nodo(1, 2, 3)
    assert not editor.puede_rehacer


def test_operacion_invalida_no_cambia_nada(editor):
    editor.marco_desde_rejilla("C40x40", "V25x50")
    antes = editor.modelo
    with pytest.raises(ValueError, match="no existe"):
        editor.asignar_seccion(["C1"], "NO-EXISTE")
    with pytest.raises(ValueError, match="mismo nodo"):
        editor.agregar_barra("A1-N1", (0.0, 0.0, 3.5), "C40x40")
    assert editor.modelo is antes and editor.texto_deshacer == "Marco desde rejilla"


def test_barras_por_puntos_tipos_y_nombres(editor):
    c = editor.agregar_barra((0, 0, 3.5), (0, 0, 0), "C40x40")
    v = editor.agregar_barra((0, 0, 3.5), (6, 0, 3.5), "V25x50")
    d = editor.agregar_barra((0, 0, 0), (6, 0, 3.5), "V25x50")
    m = editor.modelo
    assert (c, v, d) == ("C1", "V1", "D1")
    assert m.barra("C1").i == "A1-Base"  # las columnas van hacia arriba
    assert m.barra("D1").tipo == "contraviento"
    assert editor.agregar_barra("B1-N1", "A1-N1", "V25x50") == "V1"  # ya existía
    assert editor.agregar_nodo(1.0, 1.0, 1.0) == "N1"


def test_renombrar_propaga_referencias(editor):
    editor.marco_desde_rejilla("C40x40", "V25x50")
    editor.asignar_carga_nodal(["A1-N2"], "CV", (10, 0, 0, 0, 0, 0))
    editor.editar_nodo("A1-N2", id_nuevo="esquina")
    editor.editar_barra("C1", id="C-A1", rotacion=90)
    m = editor.modelo
    assert m.cargas_nodales[0].nodo == "esquina" and m.barra("C-A1").rotacion == 90
    assert any(b.j == "esquina" for b in m.barras)
    with pytest.raises(ValueError, match="ya hay un nodo"):
        editor.editar_nodo("esquina", z=3.5, x=0, y=0)

    filas = dfn.filas("patrones", m)
    filas[0][0] = "Muerta"
    editor.reemplazar("patrones", dfn.objetos("patrones", filas), {"CM": "Muerta"})
    m = editor.modelo
    assert m.combinaciones[1].factores == {"Muerta": 1.3, "CV": 1.5} and m.fuente_masa == {"Muerta": 1.0}

    filas = dfn.filas("secciones", m)
    filas[0][0] = "C50x50"
    filas[0][3:5] = ["0.5", "0.5"]
    editor.reemplazar("secciones", dfn.objetos("secciones", filas), {"C40x40": "C50x50"})
    assert editor.modelo.barra("C2").seccion == "C50x50"


def test_apoyos_y_cargas_se_reemplazan(editor):
    editor.agregar_nodo(0, 0, 0)
    editor.asignar_apoyo(["A1-Base"], (True, True, True, False, False, False))
    editor.asignar_apoyo(["A1-Base"], (True,) * 6)
    assert len(editor.modelo.apoyos) == 1 and all(editor.modelo.apoyos[0].restricciones)
    editor.asignar_apoyo(["A1-Base"], None)
    assert editor.modelo.apoyos == []
    editor.asignar_carga_nodal(["A1-Base"], "CM", (0, 0, -5, 0, 0, 0))
    editor.asignar_carga_nodal(["A1-Base"], "CM", (0, 0, -7, 0, 0, 0))
    assert [c.fuerzas[2] for c in editor.modelo.cargas_nodales] == [-7]
    editor.asignar_carga_nodal(["A1-Base"], "CM", (0,) * 6)
    assert editor.modelo.cargas_nodales == []


def test_guardar_y_reabrir(editor, tmp_path):
    editor.marco_desde_rejilla("C40x40", "V25x50")
    ruta = tmp_path / "m.json"
    editor.modelo.guardar(str(ruta))
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["rejilla"]["ejes_x"][1] == {"nombre": "B", "coord": 6.0}
    assert Edificio.cargar(str(ruta)) == editor.modelo


def test_tablas_de_definir():
    assert dfn.leer_factores("1.3*CM + 1.5*CV") == {"CM": 1.3, "CV": 1.5}
    assert dfn.leer_factores("CM + -1*SX") == {"CM": 1.0, "SX": -1.0}
    assert dfn.leer_lista("3x6, 8") == [6, 6, 6, 8]
    with pytest.raises(ValueError, match="fila 1"):
        dfn.objetos("materiales", [["Acero", "acero", "-5", "0.3", "77"]])
    secs = dfn.objetos("secciones", [["W", "general", "A36", "", "", "0.01", "2e-4", "1e-5", "1e-7"]])
    assert secs[0].I33 == 2e-4


def test_seleccion_en_pantalla():
    # Cámara trivial: x, y del mundo en [-1, 1] ocupan toda la pantalla de 200 x 100
    matriz = np.eye(4)
    nodos = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.0]])
    barras = np.array([[[-1.0, -0.5, 0.0], [1.0, -0.5, 0.0]]])
    rejilla = np.array([[-0.5, 0.5, 0.0]])
    assert elegir((100, 50), nodos, barras, rejilla, matriz, 200, 100) == ("nodo", 0)
    assert elegir((153, 75), nodos, barras, rejilla, matriz, 200, 100) == ("nodo", 1)
    assert elegir((40, 27), nodos, barras, rejilla, matriz, 200, 100) == ("barra", 0)
    assert elegir((52, 74), nodos, barras, rejilla, matriz, 200, 100) == ("punto", 0)
    assert elegir((10, 90), nodos, barras, rejilla, matriz, 200, 100) is None
