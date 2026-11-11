"""Selección con el ratón en la vista 3D, hecha en coordenadas de pantalla.

En lugar de los selectores de VTK (que dependen del búfer de dibujo), se proyectan los nodos,
las barras y los puntos de la rejilla con la matriz de la cámara y se busca el más cercano al
clic. Así el resultado no depende de la tarjeta gráfica y se prueba sin pantalla.
"""

from __future__ import annotations

import numpy as np

RADIO_NODO = 10.0  # px
RADIO_BARRA = 6.0  # px


def proyectar(puntos: np.ndarray, matriz: np.ndarray, ancho: float, alto: float) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas de pantalla (px, origen abajo a la izquierda, como VTK) de puntos 3D,
    y una máscara de los que quedan delante de la cámara."""
    puntos = np.asarray(puntos, dtype=float).reshape(-1, 3)
    h = np.c_[puntos, np.ones(len(puntos))] @ np.asarray(matriz, dtype=float).T
    w = h[:, 3]
    delante = w > 1e-12
    w = np.where(delante, w, 1.0)
    ndc = h[:, :2] / w[:, None]
    px = np.c_[(ndc[:, 0] + 1.0) * 0.5 * ancho, (ndc[:, 1] + 1.0) * 0.5 * alto]
    return px, delante


def distancia_a_segmentos(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distancia en pantalla del punto p a cada segmento a[k]-b[k]."""
    ab = b - a
    largo2 = np.einsum("ij,ij->i", ab, ab)
    t = np.where(largo2 > 0, np.einsum("ij,ij->i", p - a, ab) / np.where(largo2 > 0, largo2, 1.0), 0.0)
    t = np.clip(t, 0.0, 1.0)
    cerca = a + t[:, None] * ab
    return np.linalg.norm(cerca - p, axis=1)


def elegir(
    clic: tuple[float, float],
    nodos: np.ndarray,
    barras: np.ndarray,
    puntos_rejilla: np.ndarray,
    matriz: np.ndarray,
    ancho: float,
    alto: float,
) -> tuple[str, int] | None:
    """Lo que hay bajo el clic: ("nodo", k), ("barra", k) o ("punto", k) con k el índice en la
    lista correspondiente. `barras` es un arreglo (n, 2, 3) con los extremos. Tienen prioridad
    los nodos, luego las barras y al final los puntos de la rejilla."""
    p = np.asarray(clic, dtype=float)

    def mas_cercano_puntos(pts: np.ndarray) -> tuple[int, float] | None:
        if len(pts) == 0:
            return None
        px, delante = proyectar(pts, matriz, ancho, alto)
        d = np.where(delante, np.linalg.norm(px - p, axis=1), np.inf)
        k = int(np.argmin(d))
        return k, float(d[k])

    r = mas_cercano_puntos(nodos)
    if r and r[1] <= RADIO_NODO:
        return "nodo", r[0]
    if len(barras):
        b = np.asarray(barras, dtype=float)
        pa, da = proyectar(b[:, 0], matriz, ancho, alto)
        pb, db = proyectar(b[:, 1], matriz, ancho, alto)
        d = np.where(da & db, distancia_a_segmentos(p, pa, pb), np.inf)
        k = int(np.argmin(d))
        if d[k] <= RADIO_BARRA:
            return "barra", k
    r = mas_cercano_puntos(puntos_rejilla)
    if r and r[1] <= RADIO_NODO:
        return "punto", r[0]
    return None


def matriz_camara(renderer) -> np.ndarray:
    """Matriz 4x4 de mundo a coordenadas normalizadas del renderizador de VTK."""
    cam = renderer.GetActiveCamera()
    m = cam.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1, 1)
    return np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)])
