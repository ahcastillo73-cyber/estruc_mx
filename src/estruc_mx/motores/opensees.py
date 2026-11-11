"""Traductor del modelo a OpenSeesPy.

Genera un script de Python legible y autónomo que el usuario puede abrir, modificar
y ejecutar por su cuenta. La aplicación lo ejecuta en un proceso aparte: así una
caída del motor no tumba la interfaz y OpenSees nunca se enlaza con el programa.

El script imprime los resultados en JSON, en ejes globales del modelo.

Se analiza la malla de `modelo/malla.py`, la misma que usa PyNite: muros y losas como elementos
ShellMITC4 con sección ElasticMembranePlateSection (o PlateFiber con material ortótropo cuando el
módulo de cortante en el plano no es el isótropo, como en mampostería), y las barras que pasan por la malla, en tramos.
Los diafragmas rígidos usan `rigidDiaphragm` con el nodo maestro en el centro de masa.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..modelo import Edificio, masas_nodales
from ..modelo.malla import discretizar
from ..modelo.masas import peso_lineal
from .comun import combinaciones_efectivas
from .resultados import Modos, Resultados

_MARCA = "#RESULTADOS#"


def _num(v: float) -> str:
    return repr(float(v))


# Los materiales PlateFiber llevan tags aparte de los ortótropos que envuelven
_DESFASE_MAT = 100000


def _isotropo(E: float, nu: float, G: float) -> bool:
    return abs(G - E / (2 * (1 + nu))) <= 1e-9 * E


def generar_script(modelo: Edificio) -> str:
    """Devuelve el script OpenSeesPy (texto) que analiza todas las combinaciones."""
    malla = discretizar(modelo)
    tag_nodo = {nid: k for k, nid in enumerate(malla.nodos, start=1)}
    for d in malla.diafragmas:
        tag_nodo[d.maestro] = len(tag_nodo) + 1
    tag_seg = {sg.id: k for k, sg in enumerate(malla.segmentos, start=1)}
    tag_elem = {e.id: k for k, e in enumerate(malla.elementos, start=len(tag_seg) + 1)}
    tag_sec_area = {s.nombre: k for k, s in enumerate(modelo.secciones_area, start=1)}
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
    w(f"APOYOS = {json.dumps(list(malla.apoyos), ensure_ascii=False)}")
    w(f"CASCARAS = {json.dumps(tag_elem, ensure_ascii=False)}  # elementos de muros y losas")
    try:
        masas = masas_nodales(modelo, malla)
    except ValueError:
        masas = {}
    w(f"MASAS = {json.dumps({n: round(m, 12) for n, m in masas.items()}, ensure_ascii=False)}  # t, traslacional")
    w("")
    w("")
    w("def construir():")
    w("    ops.wipe()")
    w("    ops.model('basic', '-ndm', 3, '-ndf', 6)")
    for nid, p in malla.nodos.items():
        w(f"    ops.node({tag_nodo[nid]}, {_num(p[0])}, {_num(p[1])}, {_num(p[2])})  # {nid}")
    for nid, r in malla.apoyos.items():
        fijos = ", ".join("1" if x else "0" for x in r)
        w(f"    ops.fix({tag_nodo[nid]}, {fijos})")
    for d in malla.diafragmas:
        c = d.centro
        w(f"    # Diafragma rígido {d.nombre}: maestro en el centro de masa, libres UX, UY y RZ")
        w(f"    ops.node({tag_nodo[d.maestro]}, {_num(c[0])}, {_num(c[1])}, {_num(c[2])})  # {d.maestro}")
        w(f"    ops.fix({tag_nodo[d.maestro]}, 0, 0, 1, 1, 1, 0)")
        esclavos = ", ".join(str(tag_nodo[n]) for n in d.esclavos)
        w(f"    ops.rigidDiaphragm(3, {tag_nodo[d.maestro]}, {esclavos})")
    for sg in malla.segmentos:
        b = modelo.barra(sg.barra)
        s = modelo.seccion(b.seccion)
        m = modelo.material(s.material)
        _, _, z = modelo.ejes_locales(b)
        t = tag_seg[sg.id]
        w(f"    # {b.tipo} {sg.id}, sección {s.nombre}")
        w(f"    ops.geomTransf('Linear', {t}, {_num(z[0])}, {_num(z[1])}, {_num(z[2])})")
        w(
            f"    ops.element('elasticBeamColumn', {t}, {tag_nodo[sg.i]}, {tag_nodo[sg.j]}, "
            f"{_num(s.A)}, {_num(m.E)}, {_num(m.G)}, {_num(s.J)}, {_num(s.I22)}, {_num(s.I33)}, {t})"
        )
    if malla.elementos:
        w("    # Muros y losas: cáscara elástica (la masa va en los nodos, densidad 0)")
        for s in modelo.secciones_area:
            E, nu, Gp = modelo.modulos_area(s)
            tag = tag_sec_area[s.nombre]
            if _isotropo(E, nu, Gp):
                w(
                    f"    ops.section('ElasticMembranePlateSection', {tag}, "
                    f"{_num(E)}, {_num(nu)}, {_num(s.espesor)}, 0.0)  # {s.nombre}"
                )
            else:
                # Cortante en el plano distinto del isótropo (mampostería, Gm = 0.2·Em): material
                # ortótropo integrado en el espesor; el cortante transversal queda isótropo
                Ge = E / (2 * (1 + nu))
                w(f"    # {s.nombre}: G en el plano = {Gp:.6g} kPa (isótropo daría {Ge:.6g})")
                w(
                    f"    ops.nDMaterial('ElasticOrthotropic', {tag}, {_num(E)}, {_num(E)}, {_num(E)}, "
                    f"{_num(nu)}, {_num(nu)}, {_num(nu)}, {_num(Gp)}, {_num(Ge)}, {_num(Ge)}, 0.0)"
                )
                w(f"    ops.nDMaterial('PlateFiber', {tag + _DESFASE_MAT}, {tag})")
                w(f"    ops.section('PlateFiber', {tag}, {tag + _DESFASE_MAT}, {_num(s.espesor)})")
        seccion = {a.id: a.seccion for a in modelo.areas}
        for e in malla.elementos:
            nodos = ", ".join(str(tag_nodo[n]) for n in e.nodos)
            w(f"    ops.element('ShellMITC4', {tag_elem[e.id]}, {nodos}, {tag_sec_area[seccion[e.area]]})  # {e.id}")
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
        for sg in malla.segmentos_de(c.barra):
            w(
                f"    k = factores.get({c.patron!r}, 0.0)"
                f"; ops.eleLoad('-ele', {tag_seg[sg.id]}, '-type', '-beamUniform', "
                f"k * {_num(wy)}, k * {_num(wz)}, k * {_num(wx)})"
            )
    for p in modelo.patrones:
        if not p.peso_propio:
            continue
        w(f"    k = factores.get({p.nombre!r}, 0.0) * {_num(p.peso_propio)}  # peso propio")
        for sg in malla.segmentos:
            peso = peso_lineal(modelo, sg.barra)
            if peso:
                x, y, z = modelo.ejes_locales(modelo.barra(sg.barra))
                wy, wz, wx = -peso * y[2], -peso * z[2], -peso * x[2]
                w(f"    ops.eleLoad('-ele', {tag_seg[sg.id]}, '-type', '-beamUniform', k * {_num(wy)}, k * {_num(wz)}, k * {_num(wx)})")
        for nid, peso in malla.peso_areas.items():
            w(f"    ops.load({tag_nodo[nid]}, 0.0, 0.0, k * {_num(-peso)}, 0.0, 0.0, 0.0)")
    for patron, tabla in malla.cargas_area.items():
        w(f"    k = factores.get({patron!r}, 0.0)  # cargas por m² repartidas a los nodos")
        for nid, F in tabla.items():
            w(f"    ops.load({tag_nodo[nid]}, k * {_num(F[0])}, k * {_num(F[1])}, k * {_num(F[2])}, 0.0, 0.0, 0.0)")
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
    w("    return desp, reac, fuerzas_cascaras()")
    w("")
    w("")
    w("def fuerzas_cascaras():")
    w("    # Fuerzas que los nodos ejercen sobre cada elemento, ejes globales, 24 valores")
    w("    return {e: list(ops.eleForce(t)) for e, t in CASCARAS.items()}")
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
    w("    fuerzas = []")
    w("    if CASCARAS:")
    w("        # Fuerzas de cada forma modal: se impone la forma como desplazamiento")
    w("        for forma in formas:")
    w("            for n, t in NODOS.items():")
    w("                for k in range(6):")
    w("                    ops.setNodeDisp(t, k + 1, forma[n][k], '-commit')")
    w("            fuerzas.append(fuerzas_cascaras())")
    w("    return periodos, formas, fuerzas")
    w("")
    w("")
    w(f"COMBINACIONES = {json.dumps({c.nombre: c.factores for c in combos}, ensure_ascii=False)}")
    w("")
    w("if __name__ == '__main__':")
    w("    # Uso: python modelo_opensees.py            -> análisis estático de las combinaciones")
    w("    #      python modelo_opensees.py modal 12   -> análisis modal con 12 modos")
    w("    if len(sys.argv) > 1 and sys.argv[1] == 'modal':")
    w("        T, phi, fz = modal(int(sys.argv[2]) if len(sys.argv) > 2 else 12)")
    w("        salida = {'periodos': T, 'formas': phi, 'fuerzas_elementos': fz}")
    w("    else:")
    w("        salida = {'desplazamientos': {}, 'reacciones': {}, 'fuerzas_elementos': {}}")
    w("        for nombre, factores in COMBINACIONES.items():")
    w("            d, r, fz = analizar(factores)")
    w("            salida['desplazamientos'][nombre] = d")
    w("            salida['reacciones'][nombre] = r")
    w("            if fz:")
    w("                salida['fuerzas_elementos'][nombre] = fz")
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
    return Resultados(
        motor="opensees", desplazamientos=datos["desplazamientos"], reacciones=datos["reacciones"],
        fuerzas_elementos=datos["fuerzas_elementos"],
    )


def modal(modelo: Edificio, n_modos: int = 12, carpeta: str | Path | None = None, timeout: float = 600) -> Modos:
    """Análisis modal con las masas nodales de `masas_nodales` (traslacionales)."""
    if not masas_nodales(modelo):
        raise ValueError("el modelo no tiene masa: define fuente_masa, peso propio o masas nodales")
    datos = _ejecutar(modelo, ["modal", str(n_modos)], carpeta, timeout)
    return Modos(motor="opensees", periodos=datos["periodos"], formas=datos["formas"], fuerzas_elementos=datos["fuerzas_elementos"])
