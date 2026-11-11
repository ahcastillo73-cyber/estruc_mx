"""Línea de comandos de la prueba de concepto.

    estruc-mx analizar ejemplos/marco_3niveles.json --motor pynite
    estruc-mx script ejemplos/marco_3niveles.json -o modelo_opensees.py
    estruc-mx ver ejemplos/marco_3niveles.json --combinacion "1.1CM+SX"
"""

from __future__ import annotations

import argparse
import sys

from .modelo import Edificio


def _analizar(modelo: Edificio, motor: str):
    if motor == "pynite":
        from .motores import pynite

        return pynite.analizar(modelo)
    from .motores import opensees

    return opensees.analizar(modelo)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="estruc-mx", description="Análisis estructural de edificios")
    sub = p.add_subparsers(dest="orden", required=True)

    a = sub.add_parser("analizar", help="Analiza el modelo y muestra desplazamientos máximos")
    a.add_argument("modelo")
    a.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")

    s = sub.add_parser("script", help="Exporta el script OpenSeesPy del modelo")
    s.add_argument("modelo")
    s.add_argument("-o", "--salida", default="modelo_opensees.py")

    v = sub.add_parser("ver", help="Vista 3D del modelo y su deformada")
    v.add_argument("modelo")
    v.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")
    v.add_argument("--combinacion")
    v.add_argument("--sin-analisis", action="store_true", help="Solo la geometría")
    v.add_argument("--captura", help="Guardar PNG en lugar de abrir ventana")

    args = p.parse_args(argv)
    modelo = Edificio.cargar(args.modelo)

    if args.orden == "analizar":
        r = _analizar(modelo, args.motor)
        print(f"{modelo.nombre}: {len(modelo.nodos)} nodos, {len(modelo.barras)} barras, motor {r.motor}")
        for combo in r.combinaciones:
            partes = []
            for gdl, eje in enumerate("XYZ"):
                nodo, val = r.desplazamiento_maximo(combo, gdl)
                partes.append(f"U{eje} = {val * 1000:+.2f} mm ({nodo})")
            print(f"  {combo:<16} " + "   ".join(partes))
    elif args.orden == "script":
        from .motores import opensees

        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(opensees.generar_script(modelo))
        print(f"Script guardado en {args.salida}")
    elif args.orden == "ver":
        from .visual.vista3d import mostrar

        r = None if args.sin_analisis else _analizar(modelo, args.motor)
        mostrar(modelo, r, args.combinacion, captura=args.captura)
    return 0


if __name__ == "__main__":
    sys.exit(main())
