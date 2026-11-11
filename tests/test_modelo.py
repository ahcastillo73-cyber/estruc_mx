import numpy as np
import pytest

from estruc_mx.modelo import Barra, Edificio, Material, Nodo, SeccionRectangular


def test_guardar_y_cargar_conserva_el_modelo(marco, tmp_path):
    ruta = tmp_path / "marco.json"
    marco.guardar(str(ruta))
    assert Edificio.cargar(str(ruta)) == marco


def test_referencias_invalidas_se_reportan():
    with pytest.raises(ValueError, match="nodo 'B' no existe"):
        Edificio(
            nombre="malo",
            materiales=[Material(nombre="m", E=1.0)],
            secciones=[SeccionRectangular(nombre="s", material="m", b=1, h=1)],
            nodos=[Nodo(id="A", x=0, y=0, z=0)],
            barras=[Barra(id="b", i="A", j="B", seccion="s")],
        )


@pytest.mark.parametrize(
    "j, esperado_y",
    [((5, 0, 0), (0, 0, 1)), ((0, 5, 0), (0, 0, 1)), ((0, 0, 3), (-1, 0, 0)), ((0, 0, -3), (1, 0, 0))],
)
def test_ejes_locales_son_ortonormales_y_siguen_la_convencion(j, esperado_y):
    m = Edificio(
        nombre="ejes",
        materiales=[Material(nombre="m", E=1.0)],
        secciones=[SeccionRectangular(nombre="s", material="m", b=1, h=1)],
        nodos=[Nodo(id="A", x=0, y=0, z=0), Nodo(id="B", x=j[0], y=j[1], z=j[2])],
        barras=[Barra(id="b", i="A", j="B", seccion="s")],
    )
    x, y, z = m.ejes_locales(m.barras[0])
    np.testing.assert_allclose(np.cross(x, y), z, atol=1e-12)
    np.testing.assert_allclose(y, esperado_y, atol=1e-12)


def test_ejemplo_publicado_esta_al_dia(marco):
    from pathlib import Path

    ruta = Path(__file__).resolve().parent.parent / "ejemplos" / "marco_3niveles.json"
    assert Edificio.cargar(str(ruta)) == marco
