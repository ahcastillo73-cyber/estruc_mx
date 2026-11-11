"""Generadores de modelos a partir de ejes y niveles (como la rejilla de ETABS)."""

from __future__ import annotations

from .edificio import Apoyo, Barra, Edificio, Nodo


def marco_regular(
    nombre: str,
    ejes_x: list[float],
    ejes_y: list[float],
    alturas: list[float],
    seccion_columna: str,
    seccion_viga: str,
    **kwargs,
) -> Edificio:
    """Crea un marco 3D regular: columnas en cada cruce de ejes y vigas en ambas direcciones.

    `ejes_x`, `ejes_y`: coordenadas de los ejes (m). `alturas`: altura de cada entrepiso (m).
    Los nodos se nombran `N{ix}-{iy}-{nivel}`; columnas `C...`, vigas `VX...` y `VY...`.
    Los demás argumentos (materiales, secciones, patrones...) pasan directo a `Edificio`.
    """
    niveles = [0.0]
    for h in alturas:
        niveles.append(niveles[-1] + h)

    def nid(ix: int, iy: int, k: int) -> str:
        return f"N{ix}-{iy}-{k}"

    nodos = [
        Nodo(id=nid(ix, iy, k), x=x, y=y, z=z)
        for k, z in enumerate(niveles)
        for iy, y in enumerate(ejes_y)
        for ix, x in enumerate(ejes_x)
    ]
    apoyos = [Apoyo(nodo=nid(ix, iy, 0)) for iy in range(len(ejes_y)) for ix in range(len(ejes_x))]

    barras: list[Barra] = []
    for k in range(1, len(niveles)):
        for iy in range(len(ejes_y)):
            for ix in range(len(ejes_x)):
                barras.append(
                    Barra(id=f"C{ix}-{iy}-{k}", tipo="columna", i=nid(ix, iy, k - 1), j=nid(ix, iy, k), seccion=seccion_columna)
                )
        for iy in range(len(ejes_y)):
            for ix in range(len(ejes_x) - 1):
                barras.append(
                    Barra(id=f"VX{ix}-{iy}-{k}", tipo="viga", i=nid(ix, iy, k), j=nid(ix + 1, iy, k), seccion=seccion_viga)
                )
        for ix in range(len(ejes_x)):
            for iy in range(len(ejes_y) - 1):
                barras.append(
                    Barra(id=f"VY{ix}-{iy}-{k}", tipo="viga", i=nid(ix, iy, k), j=nid(ix, iy + 1, k), seccion=seccion_viga)
                )

    return Edificio(nombre=nombre, nodos=nodos, barras=barras, apoyos=apoyos, **kwargs)
