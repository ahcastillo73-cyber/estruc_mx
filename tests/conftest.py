import pytest

from estruc_mx.modelo import (
    CargaDistribuida,
    CargaNodal,
    Combinacion,
    Material,
    PatronCarga,
    SeccionRectangular,
    marco_regular,
)


def construir_marco(rotacion_columnas: float = 0.0):
    """Marco de concreto 2x1 crujías, 3 niveles, con gravedad y sismo en X y Y."""
    m = marco_regular(
        "Marco de prueba",
        ejes_x=[0.0, 6.0, 12.0],
        ejes_y=[0.0, 5.0],
        alturas=[3.5, 3.0, 3.0],
        seccion_columna="C40x60",
        seccion_viga="V30x60",
        materiales=[Material(nombre="f'c 250", tipo="concreto", E=22_000_000.0, nu=0.2, peso_vol=24.0)],
        secciones=[
            SeccionRectangular(nombre="C40x60", material="f'c 250", b=0.40, h=0.60),
            SeccionRectangular(nombre="V30x60", material="f'c 250", b=0.30, h=0.60),
        ],
        patrones=[PatronCarga(nombre="CM", tipo="muerta"), PatronCarga(nombre="SX", tipo="sismo"), PatronCarga(nombre="SY", tipo="sismo")],
        combinaciones=[
            Combinacion(nombre="CM", factores={"CM": 1.0}),
            Combinacion(nombre="1.1CM+SX", factores={"CM": 1.1, "SX": 1.0}),
            Combinacion(nombre="1.1CM+SY", factores={"CM": 1.1, "SY": 1.0}),
        ],
    )
    for b in m.barras:
        if b.tipo == "viga":
            m.cargas_distribuidas.append(CargaDistribuida(patron="CM", barra=b.id, direccion="Z", w=-20.0))
        elif rotacion_columnas:
            b.rotacion = rotacion_columnas
    for k, F in [(1, 30.0), (2, 60.0), (3, 90.0)]:
        m.cargas_nodales.append(CargaNodal(patron="SX", nodo=f"N0-0-{k}", fuerzas=(F, 0, 0, 0, 0, 0)))
        m.cargas_nodales.append(CargaNodal(patron="SY", nodo=f"N2-1-{k}", fuerzas=(0, F, 0, 0, 0, 0)))
    return type(m).model_validate(m.model_dump())


@pytest.fixture
def marco():
    return construir_marco()
