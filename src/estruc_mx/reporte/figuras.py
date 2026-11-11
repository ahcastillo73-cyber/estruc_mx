"""Figuras del reporte con matplotlib, sin ventana (se generan PNG en memoria).

Se usa matplotlib y no la vista VTK para que el reporte funcione en cualquier máquina,
también sin pantalla ni tarjeta gráfica (servidores, CI).
"""

from __future__ import annotations

import io

import numpy as np
from matplotlib.figure import Figure

from ..modelo import Edificio

DPI = 200
GRIS = "#9a9a9a"
AZUL = "#1f5fa8"
ROJO = "#c0392b"
NARANJA = "#d9822b"
COLORES_AREA = {"muro": "#d8a26b", "losa": "#8fb8de"}


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight")
    return buf.getvalue()


def escala_deformada(modelo: Edificio, desplazamientos: dict[str, list[float]], fraccion: float = 0.08) -> float:
    """Factor para que el mayor desplazamiento se vea como `fraccion` del tamaño del edificio."""
    puntos = np.array([n.coords for n in modelo.nodos])
    tamano = float(np.ptp(puntos, axis=0).max()) or 1.0
    dmax = max((float(np.linalg.norm(v[:3])) for v in desplazamientos.values()), default=0.0)
    return fraccion * tamano / dmax if dmax > 0 else 0.0


def _ejes_iguales(ax, puntos: np.ndarray) -> None:
    centro = (puntos.max(axis=0) + puntos.min(axis=0)) / 2
    r = float(np.ptp(puntos, axis=0).max()) / 2 or 1.0
    ax.set_xlim(centro[0] - r, centro[0] + r)
    ax.set_ylim(centro[1] - r, centro[1] + r)
    ax.set_zlim(centro[2] - r, centro[2] + r)
    ax.set_box_aspect((1, 1, 1))


def deformada(
    modelo: Edificio,
    desplazamientos: dict[str, list[float]] | None = None,
    titulo: str = "",
    escala: float | None = None,
) -> tuple[bytes, float]:
    """Vista isométrica del modelo y, si se dan desplazamientos, de la deformada.
    Devuelve el PNG y la escala usada."""
    fig = Figure(figsize=(6.0, 5.0))
    ax = fig.add_subplot(projection="3d")
    from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

    pos = {n.id: n.coords for n in modelo.nodos}
    esc = 0.0
    if desplazamientos:
        esc = escala if escala is not None else escala_deformada(modelo, desplazamientos)
    colores = {"columna": AZUL, "viga": "#2e7d32", "contraviento": NARANJA}
    if modelo.areas:
        caras = [[pos[n] for n in a.nodos] for a in modelo.areas]
        relleno = [COLORES_AREA[a.tipo] for a in modelo.areas]
        ax.add_collection3d(Poly3DCollection(
            caras, facecolors=relleno, edgecolors="#8a7a65", linewidths=0.5, alpha=0.12 if desplazamientos else 0.35,
        ))
    if desplazamientos:
        from ..modelo.malla import discretizar

        malla = discretizar(modelo)
        p = {n: c + esc * np.asarray(desplazamientos.get(n, [0.0] * 6)[:3]) for n, c in malla.nodos.items()}
        ax.add_collection3d(Line3DCollection([[malla.nodos[s.i], malla.nodos[s.j]] for s in malla.segmentos], colors=GRIS, linewidths=0.8, alpha=0.6))
        ax.add_collection3d(Line3DCollection([[p[s.i], p[s.j]] for s in malla.segmentos], colors=ROJO, linewidths=1.6))
        if malla.elementos:
            ax.add_collection3d(Line3DCollection(
                [[p[e.nodos[k]], p[e.nodos[(k + 1) % 4]]] for e in malla.elementos for k in range(4)],
                colors=ROJO, linewidths=0.3, alpha=0.45,
            ))
    else:
        for b in modelo.barras:
            ax.plot(*zip(pos[b.i], pos[b.j]), color=colores.get(b.tipo, "#555555"), lw=1.4)
    apoyos = np.array([pos[a.nodo] for a in modelo.apoyos]) if modelo.apoyos else np.empty((0, 3))
    if len(apoyos):
        ax.scatter(apoyos[:, 0], apoyos[:, 1], apoyos[:, 2], marker="s", s=14, color="black")
    _ejes_iguales(ax, np.array(list(pos.values())))
    ax.view_init(elev=22, azim=-58)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.tick_params(labelsize=7)
    if titulo:
        ax.set_title(titulo, fontsize=10)
    return _png(fig), esc


def espectro(modelo: Edificio, periodos: list[float] | None = None) -> bytes:
    """Curva Sa(T) con los periodos de los modos marcados."""
    e = modelo.espectro
    tmax = max(4.0, *(periodos or [0.0]), *(getattr(e, "T", None) or [0.0]))
    T = np.linspace(0.0, tmax * 1.05, 400)
    fig = Figure(figsize=(6.5, 3.4))
    ax = fig.add_subplot()
    ax.plot(T, [e.sa(t) for t in T], color=AZUL, lw=1.8, label=e.nombre)
    if periodos:
        validos = [t for t in periodos if np.isfinite(t) and t > 0]
        ax.scatter(validos, [e.sa(t) for t in validos], color=ROJO, s=16, zorder=3, label="Modos")
    ax.set_xlabel("Periodo T (s)")
    ax.set_ylabel("Sa (g)")
    ax.set_xlim(0, T[-1])
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _png(fig)


def derivas(niveles: list[float], por_direccion: dict[str, list[float]], limite: float | None) -> bytes:
    """Perfil de derivas (ya multiplicadas por el factor de comparación) contra el límite."""
    fig = Figure(figsize=(4.8, 4.2))
    ax = fig.add_subplot()
    estilos = {"X": (AZUL, "o"), "Y": (NARANJA, "s")}
    for d, valores in por_direccion.items():
        color, marca = estilos.get(d, ("black", "^"))
        # Distorsión constante en cada entrepiso: tramo vertical de la base al techo
        xs, zs, abajo = [], [], 0.0
        for z, v in zip(niveles, valores):
            xs += [v, v]
            zs += [abajo, z]
            abajo = z
        ax.plot(xs, zs, color=color, lw=1.6, label=f"Dirección {d}")
        ax.scatter(valores, niveles, color=color, marker=marca, s=18, zorder=3)
    if limite:
        ax.axvline(limite, color=ROJO, ls="--", lw=1.4, label=f"Límite {limite:.4f}")
    ax.set_xlabel("Distorsión de entrepiso")
    ax.set_ylabel("Elevación (m)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    return _png(fig)
