"""Vista 3D del modelo y de la deformada con PyVista (VTK)."""

from __future__ import annotations

import numpy as np

from ..modelo import Edificio
from ..motores import Resultados


def malla_barras(modelo: Edificio, resultados: Resultados | None = None, combinacion: str | None = None, escala: float = 0.0):
    """PolyData con una línea por barra. Con resultados, desplaza los nodos `escala` veces
    y guarda el desplazamiento total de cada nodo en el arreglo de puntos "desplazamiento"."""
    tabla = None
    if resultados is not None:
        tabla = resultados.desplazamientos[combinacion or resultados.combinaciones[0]]
    return malla_desde_tabla(modelo, tabla, escala)


def malla_desde_tabla(modelo: Edificio, tabla: dict[str, list[float]] | None, escala: float = 0.0):
    """Como `malla_barras`, pero con una tabla nodo -> [UX, UY, UZ, ...] cualquiera
    (por ejemplo, una forma modal)."""
    import pyvista as pv

    indice = {n.id: k for k, n in enumerate(modelo.nodos)}
    puntos = np.array([n.coords for n in modelo.nodos], dtype=float)
    desp = np.zeros_like(puntos)
    if tabla is not None:
        for nid, k in indice.items():
            desp[k] = tabla[nid][:3]
    lineas = np.array([[2, indice[b.i], indice[b.j]] for b in modelo.barras], dtype=np.int64).ravel()
    malla = pv.PolyData(puntos + escala * desp, lines=lineas)
    malla.point_data["desplazamiento"] = np.linalg.norm(desp, axis=1)
    malla.cell_data["tipo"] = [b.tipo for b in modelo.barras]
    return malla


def escala_automatica(modelo: Edificio, resultados: Resultados, combinacion: str) -> float:
    """Escala para que el máximo desplazamiento se vea como el 5 % del tamaño del edificio."""
    return escala_para_tabla(modelo, resultados.desplazamientos[combinacion])


def escala_para_tabla(modelo: Edificio, tabla: dict[str, list[float]], fraccion: float = 0.05) -> float:
    puntos = np.array([n.coords for n in modelo.nodos])
    tamano = float(np.ptp(puntos, axis=0).max()) or 1.0
    dmax = max(np.linalg.norm(v[:3]) for v in tabla.values())
    return fraccion * tamano / dmax if dmax > 0 else 0.0


def mostrar(
    modelo: Edificio,
    resultados: Resultados | None = None,
    combinacion: str | None = None,
    escala: float | None = None,
    captura: str | None = None,
) -> None:
    """Abre una ventana 3D. Con `captura`, guarda una imagen PNG sin abrir ventana."""
    import pyvista as pv

    pl = pv.Plotter(off_screen=captura is not None)
    pl.add_mesh(malla_barras(modelo), color="gray", line_width=2, opacity=0.35 if resultados else 1.0)
    titulo = modelo.nombre
    if resultados is not None:
        combo = combinacion or resultados.combinaciones[0]
        esc = escala if escala is not None else escala_automatica(modelo, resultados, combo)
        deformada = malla_barras(modelo, resultados, combo, esc)
        pl.add_mesh(
            deformada, scalars="desplazamiento", line_width=4, cmap="viridis",
            scalar_bar_args={"title": "Desplazamiento (m)"},
        )
        titulo += f" - {combo} - {resultados.motor} - escala x{esc:.0f}"
    pl.add_text(titulo, font_size=10)
    pl.add_axes()
    pl.show_grid()
    if captura:
        pl.screenshot(captura)
        pl.close()
    else:
        pl.show()
