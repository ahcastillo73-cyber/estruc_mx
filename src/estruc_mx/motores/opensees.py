"""Traductor del modelo a OpenSeesPy.

Genera un script de Python legible y autónomo que el usuario puede abrir, modificar
y ejecutar por su cuenta. La aplicación lo ejecuta en un proceso aparte: así una
caída del motor no tumba la interfaz y OpenSees nunca se enlaza con el programa.

El script imprime los resultados en JSON, en ejes globales del modelo.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..modelo import Edificio, masas_nodales
from .comun import combinaciones_efectivas
from .resultados import Modos, Resultados

_MARCA = "#RESULTADOS#"


def _num(v: float) -> str:
    return repr(float(v))


def generar_script(modelo: Edificio) -> str:
    """Devuelve el script OpenSeesPy (texto) que analiza todas las combinaciones."""
    tag_nodo = {n.id: k for k, n in enumerate(modelo.nodos, start=1)}
    tag_barra = {b.id: k for k, b in enumerate(modelo.barras, start=1)}
    combos = combinaciones_efectivas(modelo)

    L: list[str] = []
    w = L.append
    w(f'"""Modelo "{modelo.nombre}" generado por estruc_mx. Unidades: kN, m. Z vertical."""')
    w("import json")
    w("import math")
    w("import sys")
    w("")
    w("import openseespy.opensees as ops")
    w("")
    w(f"NODOS = {json.dumps(tag_nodo, ensure_ascii=False)}  # id del modelo -> tag OpenSees")
    w(f"APOYOS = {json.dumps([a.nodo for a in modelo.apoyos], ensure_ascii=False)}")
    try:
        masas = masas_nodales(modelo)
    except ValueError:
        masas = {}
    w(f"MASAS = {json.dumps({n: round(m, 12) for n, m in masas.items()}, ensure_ascii=False)}  # t, traslacional")
    w("")
    w("")
    w("def construir():")
    w("    ops.wipe()")
    w("    ops.model('basic', '-ndm', 3, '-ndf', 6)")
    for n in modelo.nodos:
        w(f"    ops.node({tag_nodo[n.id]}, {_num(n.x)}, {_num(n.y)}, {_num(n.z)})  # {n.id}")
    for a in modelo.apoyos:
        fijos = ", ".join("1" if r else "0" for r in a.restricciones)
        w(f"    ops.fix({tag_nodo[a.nodo]}, {fijos})")
    for b in modelo.barras:
        s = modelo.seccion(b.seccion)
        m = modelo.material(s.material)
        _, _, z = modelo.ejes_locales(b)
        t = tag_barra[b.id]
        w(f"    # {b.tipo} {b.id}, sección {s.nombre}")
        w(f"    ops.geomTransf('Linear', {t}, {_num(z[0])}, {_num(z[1])}, {_num(z[2])})")
        w(
            f"    ops.element('elasticBeamColumn', {t}, {tag_nodo[b.i]}, {tag_nodo[b.j]}, "
            f"{_num(s.A)}, {_num(m.E)}, {_num(m.G)}, {_num(s.J)}, {_num(s.I22)}, {_num(s.I33)}, {t})"
        )
    w("")
    w("")
    w("def cargas(factores):")
    w("    ops.timeSeries('Constant', 1)")
    w("    ops.pattern('Plain', 1, 1)")
    for c in modelo.cargas_nodales:
        vals = ", ".join(f"f[{k}]" for k in range(6))
        w(f"    f = [factores.get({c.patron!r}, 0.0) * v for v in {list(c.fuerzas)!r}]")
        w(f"    ops.load({tag_nodo[c.nodo]}, {vals})")
    for c in modelo.cargas_distribuidas:
        b = modelo.barra(c.barra)
        x, y, z = modelo.ejes_locales(b)
        g = {"X": 0, "Y": 1, "Z": 2}[c.direccion]
        wy, wz, wx = c.w * y[g], c.w * z[g], c.w * x[g]
        w(
            f"    k = factores.get({c.patron!r}, 0.0)"
            f"; ops.eleLoad('-ele', {tag_barra[b.id]}, '-type', '-beamUniform', "
            f"k * {_num(wy)}, k * {_num(wz)}, k * {_num(wx)})"
        )
    w("    pass")
    w("")
    w("")
    w("def analizar(factores):")
    w("    construir()")
    w("    cargas(factores)")
    w("    ops.system('UmfPack')")
    w("    ops.numberer('RCM')")
    w("    ops.constraints('Transformation')")
    w("    ops.integrator('LoadControl', 1.0)")
    w("    ops.algorithm('Linear')")
    w("    ops.analysis('Static')")
    w("    if ops.analyze(1) != 0:")
    w("        raise RuntimeError('El análisis no convergió')")
    w("    ops.reactions()")
    w("    desp = {n: [ops.nodeDisp(t, k) for k in range(1, 7)] for n, t in NODOS.items()}")
    w("    reac = {n: [ops.nodeReaction(NODOS[n], k) for k in range(1, 7)] for n in APOYOS}")
    w("    return desp, reac")
    w("")
    w("")
    w("def modal(n_modos):")
    w("    construir()")
    w("    for n, m in MASAS.items():")
    w("        ops.mass(NODOS[n], m, m, m, 0.0, 0.0, 0.0)")
    w("    try:")
    w("        lam = ops.eigen(n_modos)")
    w("    except Exception:")
    w("        lam = ops.eigen('-fullGenLapack', n_modos)")
    w("    periodos = [2 * math.pi / math.sqrt(v) for v in lam]")
    w("    formas = [{n: [ops.nodeEigenvector(t, i, k) for k in range(1, 7)] for n, t in NODOS.items()}")
    w("              for i in range(1, len(lam) + 1)]")
    w("    return periodos, formas")
    w("")
    w("")
    w(f"COMBINACIONES = {json.dumps({c.nombre: c.factores for c in combos}, ensure_ascii=False)}")
    w("")
    w("if __name__ == '__main__':")
    w("    # Uso: python modelo_opensees.py            -> análisis estático de las combinaciones")
    w("    #      python modelo_opensees.py modal 12   -> análisis modal con 12 modos")
    w("    if len(sys.argv) > 1 and sys.argv[1] == 'modal':")
    w("        T, phi = modal(int(sys.argv[2]) if len(sys.argv) > 2 else 12)")
    w("        salida = {'periodos': T, 'formas': phi}")
    w("    else:")
    w("        salida = {'desplazamientos': {}, 'reacciones': {}}")
    w("        for nombre, factores in COMBINACIONES.items():")
    w("            d, r = analizar(factores)")
    w("            salida['desplazamientos'][nombre] = d")
    w("            salida['reacciones'][nombre] = r")
    w(f"    print({_MARCA!r} + json.dumps(salida))")
    return "\n".join(L) + "\n"


def _ejecutar(modelo: Edificio, args: list[str], carpeta, timeout: float) -> dict:
    script = generar_script(modelo)
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(carpeta or tmp) / "modelo_opensees.py"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ruta), *args], capture_output=True, text=True, timeout=timeout
        )
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSees falló:\n{proc.stderr[-4000:]}")
    linea = next((ln for ln in proc.stdout.splitlines() if ln.startswith(_MARCA)), None)
    if linea is None:
        raise RuntimeError(f"OpenSees no devolvió resultados:\n{proc.stdout[-4000:]}")
    return json.loads(linea[len(_MARCA):])


def analizar(modelo: Edificio, carpeta: str | Path | None = None, timeout: float = 600) -> Resultados:
    """Genera el script, lo ejecuta en un proceso aparte y lee los resultados."""
    datos = _ejecutar(modelo, [], carpeta, timeout)
    return Resultados(motor="opensees", desplazamientos=datos["desplazamientos"], reacciones=datos["reacciones"])


def modal(modelo: Edificio, n_modos: int = 12, carpeta: str | Path | None = None, timeout: float = 600) -> Modos:
    """Análisis modal con las masas nodales de `masas_nodales` (traslacionales)."""
    if not masas_nodales(modelo):
        raise ValueError("el modelo no tiene masa: define fuente_masa, peso propio o masas nodales")
    datos = _ejecutar(modelo, ["modal", str(n_modos)], carpeta, timeout)
    return Modos(motor="opensees", periodos=datos["periodos"], formas=datos["formas"])
