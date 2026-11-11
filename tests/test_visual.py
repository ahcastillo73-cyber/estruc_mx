import numpy as np
import pytest

pv = pytest.importorskip("pyvista", reason="pyvista no está instalado")

from estruc_mx.motores import pynite  # noqa: E402
from estruc_mx.visual.vista3d import escala_automatica, malla_barras  # noqa: E402


def test_malla_tiene_una_linea_por_barra_y_se_deforma(marco):
    r = pynite.analizar(marco)
    base = malla_barras(marco)
    assert base.n_points == len(marco.nodos)
    assert base.n_lines == len(marco.barras)
    esc = escala_automatica(marco, r, "1.1CM+SX")
    deformada = malla_barras(marco, r, "1.1CM+SX", esc)
    assert deformada.point_data["desplazamiento"].max() > 0
    movimiento = np.linalg.norm(deformada.points - base.points, axis=1).max()
    assert movimiento == pytest.approx(0.05 * 12.0, rel=1e-6)
