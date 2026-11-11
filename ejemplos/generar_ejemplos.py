"""Regenera los modelos de ejemplo en JSON: python ejemplos/generar_ejemplos.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from conftest import construir_marco  # noqa: E402

from estruc_mx.modelo import Combinacion, Editor, EspectroNTC, Rejilla, SeccionRectangular  # noqa: E402

AQUI = Path(__file__).resolve().parent


def casa_mamposteria():
    """Casa de mampostería confinada de dos niveles: muros de tabique en los ejes, castillos
    y dalas de concreto, losas macizas de 10 cm. Cargas y espectro ilustrativos."""
    ed = Editor()
    ed.nuevo("Casa de mampostería confinada", Rejilla.regular([4.0, 3.5], [3.5, 3.0], [2.6, 2.6]))
    m = ed.modelo
    secciones = [
        *m.secciones,
        SeccionRectangular(nombre="Castillo 15x15", material="Concreto f'c 250", b=0.15, h=0.15),
        SeccionRectangular(nombre="Dala 15x20", material="Concreto f'c 250", b=0.15, h=0.20),
    ]
    ed.reemplazar("secciones", secciones)
    ed.marco_desde_rejilla("Castillo 15x15", "Dala 15x20")
    ed.losas_desde_rejilla("Losa 10")
    muros = [
        ((0.0, 0.0), (4.0, 0.0)), ((4.0, 0.0), (7.5, 0.0)),  # eje 1
        ((0.0, 6.5), (4.0, 6.5)), ((4.0, 6.5), (7.5, 6.5)),  # eje 3
        ((0.0, 0.0), (0.0, 3.5)), ((0.0, 3.5), (0.0, 6.5)),  # eje A
        ((7.5, 0.0), (7.5, 3.5)), ((7.5, 3.5), (7.5, 6.5)),  # eje C
        ((4.0, 0.0), (4.0, 3.5)),  # eje B, entre 1 y 2
    ]
    # NTC Mampostería 3.1.1.2.1 a): hasta tres niveles, los muros del primero se analizan
    # agrietados, con 0.5·Gm (3.1.1.2.3)
    base = m.seccion_area("Muro tabique 14")
    agrietado = base.model_copy(update={"nombre": "Muro tabique 14 agrietado", "mod_cortante": 0.5})
    ed.reemplazar("secciones_area", [*ed.modelo.secciones_area, agrietado])
    for (z0, z1), sec in (((0.0, 2.6), agrietado.nombre), ((2.6, 5.2), "Muro tabique 14")):
        for p, q in muros:
            ed.agregar_muro(p, q, z0, z1, sec)
    losas = [a.id for a in ed.modelo.areas if a.tipo == "losa"]
    ed.asignar_carga_area(losas, "CM", "Z", -2.5)  # acabados, instalaciones y muros divisorios
    ed.asignar_carga_area(losas, "CV", "Z", -1.9)  # habitación, carga viva máxima
    ed.definir_masa({"CM": 1.0, "CV": 0.5}, True)
    ed.reemplazar("combinaciones", [
        Combinacion(nombre="CM+CV", factores={"CM": 1.0, "CV": 1.0}),
        Combinacion(nombre="1.3CM+1.5CV", factores={"CM": 1.3, "CV": 1.5}),
    ])
    ed.definir_espectro(EspectroNTC(nombre="Ilustrativo (Q'R = 3)", a0=0.15, c=0.45, Ta=0.4, Tb=1.2, k=1.0, reduccion=3.0))
    ed.definir_malla(0.65)
    return ed.modelo


construir_marco().guardar(str(AQUI / "marco_3niveles.json"))
print("ejemplos/marco_3niveles.json actualizado")
casa_mamposteria().guardar(str(AQUI / "casa_mamposteria.json"))
print("ejemplos/casa_mamposteria.json actualizado")
