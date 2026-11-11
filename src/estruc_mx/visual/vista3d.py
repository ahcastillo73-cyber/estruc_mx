"""Vista 3D del modelo y de la deformada con PyVista (VTK)."""

from __future__ import annotations

from dataclasses import dataclass, field

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


COLORES_AREA = {"muro": "#d8a26b", "losa": "#8fb8de"}


def malla_areas(modelo: Edificio, areas=None):
    """PolyData con un polígono por muro o losa (sin deformar), con el arreglo de celdas "tipo"."""
    import pyvista as pv

    areas = modelo.areas if areas is None else areas
    indice = {n.id: n.coords for n in modelo.nodos}
    puntos = np.array([indice[n] for a in areas for n in a.nodos], dtype=float).reshape(-1, 3)
    caras = np.array([[4, 4 * k, 4 * k + 1, 4 * k + 2, 4 * k + 3] for k in range(len(areas))], dtype=np.int64).ravel()
    malla = pv.PolyData(puntos, faces=caras)
    malla.cell_data["tipo"] = [a.tipo for a in areas]
    return malla


def malla_deformada(modelo: Edificio, tabla: dict[str, list[float]], escala: float, malla=None):
    """Deformada con la malla de análisis: (líneas de los tramos de barra, cuadriláteros de
    muros y losas o None). Ambas llevan el arreglo de puntos "desplazamiento"."""
    import pyvista as pv

    from ..modelo.malla import discretizar

    malla = malla or discretizar(modelo)
    ids = list(malla.nodos)
    indice = {n: k for k, n in enumerate(ids)}
    puntos = np.array([malla.nodos[n] for n in ids], dtype=float)
    desp = np.array([tabla.get(n, [0.0] * 6)[:3] for n in ids], dtype=float)
    def_ = puntos + escala * desp
    norma = np.linalg.norm(desp, axis=1)
    lineas = None
    if malla.segmentos:
        lineas = pv.PolyData(def_, lines=np.array([[2, indice[s.i], indice[s.j]] for s in malla.segmentos], dtype=np.int64).ravel())
        lineas.point_data["desplazamiento"] = norma
    cuads = None
    if malla.elementos:
        cuads = pv.PolyData(def_, faces=np.array([[4, *(indice[n] for n in e.nodos)] for e in malla.elementos], dtype=np.int64).ravel())
        cuads.point_data["desplazamiento"] = norma
    return lineas, cuads


def malla_rejilla(rejilla, margen: float = 1.0):
    """Líneas de la rejilla en cada nivel y puntos con los nombres de los ejes (en el nivel
    más bajo, un poco afuera del edificio). Devuelve (líneas, etiquetas) o (None, None)."""
    import pyvista as pv

    if not rejilla.ejes_x or not rejilla.ejes_y or not rejilla.niveles:
        return None, None
    x0, x1 = rejilla.ejes_x[0].coord - margen, rejilla.ejes_x[-1].coord + margen
    y0, y1 = rejilla.ejes_y[0].coord - margen, rejilla.ejes_y[-1].coord + margen
    puntos = []
    for nv in rejilla.niveles:
        for e in rejilla.ejes_x:
            puntos += [(e.coord, y0, nv.z), (e.coord, y1, nv.z)]
        for e in rejilla.ejes_y:
            puntos += [(x0, e.coord, nv.z), (x1, e.coord, nv.z)]
    n = len(puntos) // 2
    lineas = pv.PolyData(np.array(puntos, dtype=float), lines=np.array([[2, 2 * k, 2 * k + 1] for k in range(n)], dtype=np.int64).ravel())
    z = rejilla.niveles[0].z
    pos = [(e.coord, y0 - 0.3 * margen, z) for e in rejilla.ejes_x] + [(x0 - 0.3 * margen, e.coord, z) for e in rejilla.ejes_y]
    etiquetas = pv.PolyData(np.array(pos, dtype=float))
    etiquetas["nombre"] = [e.nombre for e in rejilla.ejes_x] + [e.nombre for e in rejilla.ejes_y]
    return lineas, etiquetas


# --- cargas ------------------------------------------------------------------------------
@dataclass
class Flechas:
    """Flechas de carga: cada una va de `origenes[k]` a `origenes[k] + vectores[k]` (la punta
    toca el nodo, la barra o el área cargada), más textos con el valor."""

    origenes: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    vectores: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    posiciones: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    textos: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.origenes)


COLORES_CARGA = {"nodal": "#c0392b", "barra": "#d35400", "area": "#16a085"}
_EJE = {"X": 0, "Y": 1, "Z": 2}


def flechas_cargas(modelo: Edificio, patron: str, largo: float | None = None) -> dict[str, Flechas]:
    """Flechas de las cargas de un patrón: "nodal" (fuerzas en nodos), "barra" (distribuidas,
    varias flechas a lo largo de cada barra) y "area" (por m², una rejilla de flechas sobre cada
    muro o losa). El largo de cada flecha es proporcional al valor dentro de su tipo de carga, y
    la mayor mide `largo` (6 % del tamaño del edificio si no se indica). Los momentos nodales
    solo aparecen como texto."""
    if largo is None:
        P = np.array([n.coords for n in modelo.nodos]).reshape(-1, 3)
        largo = 0.06 * (float(np.ptp(P, axis=0).max()) if len(P) else 1.0) or 0.3
    coords = {n.id: n.coords for n in modelo.nodos}
    out: dict[str, Flechas] = {}

    # Fuerzas en nodos (se suman si hay varias en el mismo nodo)
    por_nodo: dict[str, np.ndarray] = {}
    for c in modelo.cargas_nodales:
        if c.patron == patron:
            por_nodo[c.nodo] = por_nodo.get(c.nodo, np.zeros(6)) + np.array(c.fuerzas, dtype=float)
    fmax = max((np.linalg.norm(v[:3]) for v in por_nodo.values()), default=0.0)
    f = Flechas()
    o, v, pos, txt = [], [], [], []
    for nid, F in por_nodo.items():
        p, mag = coords[nid], float(np.linalg.norm(F[:3]))
        partes = []
        if mag > 0:
            vec = F[:3] / fmax * largo
            o.append(p - vec)
            v.append(vec)
            partes.append(f"{mag:.3g} kN")
        mm = float(np.linalg.norm(F[3:]))
        if mm > 0:
            partes.append(f"M {mm:.3g} kN·m")
        if partes:
            pos.append(p - F[:3] / fmax * largo if mag > 0 else p)
            txt.append(", ".join(partes))
    out["nodal"] = _flechas(o, v, pos, txt)

    # Distribuidas en barras: 5 flechas por barra
    cargas = [c for c in modelo.cargas_distribuidas if c.patron == patron and c.w]
    wmax = max((abs(c.w) for c in cargas), default=0.0)
    o, v, pos, txt = [], [], [], []
    for c in cargas:
        b = modelo.barra(c.barra)
        pi, pj = coords[b.i], coords[b.j]
        vec = np.zeros(3)
        vec[_EJE[c.direccion]] = c.w / wmax * largo
        for t in np.linspace(0.0, 1.0, 5):
            q = pi + t * (pj - pi)
            o.append(q - vec)
            v.append(vec)
        pos.append(0.5 * (pi + pj) - vec)
        txt.append(f"{c.w:g} kN/m")
    out["barra"] = _flechas(o, v, pos, txt)

    # Por m² en muros y losas: rejilla de 3 × 3 flechas
    cargas = [c for c in modelo.cargas_area if c.patron == patron and c.w]
    wmax = max((abs(c.w) for c in cargas), default=0.0)
    o, v, pos, txt = [], [], [], []
    for c in cargas:
        e = modelo.esquinas(modelo.area(c.area))
        vec = np.zeros(3)
        vec[_EJE[c.direccion]] = c.w / wmax * largo
        for s_ in (0.2, 0.5, 0.8):
            for t in (0.2, 0.5, 0.8):
                q = (1 - s_) * (1 - t) * e[0] + s_ * (1 - t) * e[1] + s_ * t * e[2] + (1 - s_) * t * e[3]
                o.append(q - vec)
                v.append(vec)
        pos.append(e.mean(axis=0) - vec)
        txt.append(f"{c.w:g} kN/m²")
    out["area"] = _flechas(o, v, pos, txt)
    return out


def _flechas(o, v, pos, txt) -> Flechas:
    return Flechas(
        np.array(o, dtype=float).reshape(-1, 3), np.array(v, dtype=float).reshape(-1, 3),
        np.array(pos, dtype=float).reshape(-1, 3), list(txt),
    )


def malla_flechas(fl: Flechas):
    """PolyData con una flecha 3D por carga (para `add_mesh`), o None si no hay."""
    import pyvista as pv

    if not len(fl):
        return None
    puntos = pv.PolyData(fl.origenes)
    puntos["vector"] = fl.vectores
    puntos["largo"] = np.linalg.norm(fl.vectores, axis=1)
    return puntos.glyph(orient="vector", scale="largo", factor=1.0, geom=pv.Arrow(tip_length=0.3, tip_radius=0.12, shaft_radius=0.035))


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
    if modelo.barras:
        pl.add_mesh(malla_barras(modelo), color="gray", line_width=2, opacity=0.35 if resultados else 1.0)
    for tipo, color in COLORES_AREA.items():
        sub = [a for a in modelo.areas if a.tipo == tipo]
        if sub:
            pl.add_mesh(malla_areas(modelo, sub), color=color, opacity=0.15 if resultados else 0.5, show_edges=True)
    titulo = modelo.nombre
    if resultados is not None:
        combo = combinacion or resultados.combinaciones[0]
        esc = escala if escala is not None else escala_automatica(modelo, resultados, combo)
        lineas, cuads = malla_deformada(modelo, resultados.desplazamientos[combo], esc)
        barra = {"title": "Desplazamiento (m)"}
        for parte, ancho in ((cuads, None), (lineas, 4)):
            if parte is not None:
                pl.add_mesh(parte, scalars="desplazamiento", cmap="viridis", scalar_bar_args=barra,
                            **({"line_width": ancho} if ancho else {"show_edges": True, "opacity": 0.85}))
        titulo += f" - {combo} - {resultados.motor} - escala x{esc:.0f}"
    pl.add_text(titulo, font_size=10)
    pl.add_axes()
    pl.show_grid()
    if captura:
        pl.screenshot(captura)
        pl.close()
    else:
        pl.show()
