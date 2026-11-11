"""Línea de comandos de la prueba de concepto.

    estruc-mx analizar ejemplos/marco_3niveles.json --motor pynite
    estruc-mx analizar ejemplos/casa_mamposteria.json --motor opensees
    estruc-mx script ejemplos/marco_3niveles.json -o modelo_opensees.py
    estruc-mx ver ejemplos/marco_3niveles.json --combinacion "1.1CM+SX"
    estruc-mx modal ejemplos/marco_3niveles.json --modos 12
    estruc-mx espectral ejemplos/marco_3niveles.json --direccion X --metodo CQC
    estruc-mx gui ejemplos/marco_3niveles.json
    estruc-mx reporte ejemplos/marco_3niveles.json -o reporte.pdf --sistema marco_concreto_alta --ts 1.2
    estruc-mx mamposteria ejemplos/casa_mamposteria.json
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

    mo = sub.add_parser("modal", help="Periodos y participación de masa")
    mo.add_argument("modelo")
    mo.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")
    mo.add_argument("--modos", type=int, default=12)

    es = sub.add_parser("espectral", help="Análisis modal espectral con el espectro del modelo")
    es.add_argument("modelo")
    es.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")
    es.add_argument("--modos", type=int, default=12)
    es.add_argument("--direccion", choices=["X", "Y"], default="X")
    es.add_argument("--metodo", choices=["CQC", "SRSS"], default="CQC")

    ma = sub.add_parser("mamposteria", help="Revisa los muros de mampostería (NTC Mampostería 2023)")
    ma.add_argument("modelo")
    ma.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")
    ma.add_argument("--modos", type=int, default=12)
    ma.add_argument("--detalle", action="store_true", help="Lista todas las revisiones, no solo las que no cumplen")

    g = sub.add_parser("gui", help="Abre la aplicación de escritorio")
    g.add_argument("modelo", nargs="?")

    re = sub.add_parser("reporte", help="Reporte PDF o Word con modelo, cargas, modal, espectral y derivas")
    re.add_argument("modelo", nargs="?")
    re.add_argument("-o", "--salida", default="reporte.pdf", help="Archivo .pdf o .docx")
    re.add_argument("--motor", choices=["pynite", "opensees"], default="pynite")
    re.add_argument("--modos", type=int, default=12)
    re.add_argument("--metodo", choices=["CQC", "SRSS"], default="CQC")
    re.add_argument("--sistema", help="Sistema estructural para la distorsión límite NTC (ver --sistemas)")
    re.add_argument("--deriva-limite", type=float, help="Distorsión límite explícita")
    re.add_argument("--factor-deriva", type=float,
                    help="Factor Q·R para comparar derivas; por defecto la reducción del espectro")
    re.add_argument("--norma", choices=["NTC", "CFE"], default="NTC", help="Criterios de la revisión sísmica")
    re.add_argument("--grupo", choices=["A", "B"], default="B",
                    help="Grupo de la construcción: A revisa Ocupación Inmediata; B, Limitación de Daño")
    re.add_argument("--zona", choices=["A", "B", "C"], help="Zona sísmica, para Ks de Limitación de Daño")
    re.add_argument("--ts", type=float, help="Periodo dominante del terreno Ts (s), para el cortante mínimo NTC")
    re.add_argument("--sobrerresistencia", type=float, default=1.0, help="R′ que divide a a_min (NTC)")
    re.add_argument("--cortante-minimo", type=float, help="Coeficiente de cortante basal mínimo explícito (V/W)")
    re.add_argument("--escalar-desplazamientos", action="store_true",
                    help="Escalar también los desplazamientos por el cortante mínimo")
    re.add_argument("--sin-torsion", action="store_true", help="No considerar la torsión accidental")
    re.add_argument("--excentricidad", type=float, help="Excentricidad accidental fija, fracción de b")
    re.add_argument("--divisor-servicio", type=float,
                    help="Limitación de Daño con el espectro elástico / este valor, en lugar de Ks")
    re.add_argument("--limite-servicio", type=float, default=0.002, help="Distorsión límite de servicio")
    re.add_argument("--secciones", help="Lista separada por comas; por defecto todas")
    re.add_argument("--autor", default="")
    re.add_argument("--sistemas", action="store_true", help="Lista los sistemas estructurales y sale")

    args = p.parse_args(argv)
    if args.orden == "gui":
        from .app.ventana import main as gui

        return gui(["estruc-mx", *([args.modelo] if args.modelo else [])])
    if args.orden == "reporte" and args.sistemas:
        from .normas.ntc_sismo import DISTORSIONES_LIMITE

        print(f"  {'clave':<40} {'Q':<4} {'γSV':<7} {'γOI':<7} descripción (NTC Sismo 2023, tablas 4.3)")
        for clave, (desc, q, sv, oi) in DISTORSIONES_LIMITE.items():
            print(f"  {clave:<40} {q:<4g} {sv:<7g} {oi if oi is not None else '-':<7} {desc}")
        return 0
    if args.modelo is None:
        p.error("falta el archivo del modelo")
    modelo = Edificio.cargar(args.modelo)

    if args.orden == "analizar":
        r = _analizar(modelo, args.motor)
        areas = ""
        if modelo.areas:
            muros = sum(a.tipo == "muro" for a in modelo.areas)
            areas = f", {muros} muros, {len(modelo.areas) - muros} losas"
        print(f"{modelo.nombre}: {len(modelo.nodos)} nodos, {len(modelo.barras)} barras{areas}, motor {r.motor}")
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
    elif args.orden in ("modal", "espectral"):
        from .analisis.espectral import espectral, propiedades_modales

        if args.motor == "pynite":
            from .motores import pynite as motor
        else:
            from .motores import opensees as motor
        modos = motor.modal(modelo, args.modos)
        prop = propiedades_modales(modelo, modos)
        if args.orden == "modal":
            print(f"{modelo.nombre}: masa total {prop.masa_total:.2f} t, motor {modos.motor}")
            print("  Modo   T (s)   %Mx    %My    %Mz   acum X  acum Y")
            ax, ay = prop.fraccion_acumulada("X"), prop.fraccion_acumulada("Y")
            for i, T in enumerate(prop.periodos):
                fx, fy, fz = (prop.fraccion_masa[d][i] * 100 for d in "XYZ")
                print(f"  {i + 1:>4} {T:7.3f} {fx:6.1f} {fy:6.1f} {fz:6.1f} {ax[i] * 100:7.1f} {ay[i] * 100:7.1f}")
        else:
            r = espectral(modelo, modos, args.direccion, args.metodo)
            print(f"{modelo.nombre}: espectral {r.direccion}, {r.metodo}, motor {modos.motor}")
            print(f"  Cortante basal: {r.cortante_basal:.1f} kN")
            print("  Nivel (m)   Deriva    Columna o muro")
            for d in r.derivas:
                print(f"  {d.nivel:8.2f}  {d.deriva:8.5f}  {d.barra}")
    elif args.orden == "mamposteria":
        from .app.sesion import Sesion

        ses = Sesion(motor=args.motor)
        ses.editor.cargar(modelo)
        r = ses.revisar_mamposteria(args.modos)
        print(f"{modelo.nombre}: revisión de muros de mampostería, NTC Mampostería 2023, motor {args.motor}")
        for t in (ses.tabla_mamposteria(), ses.tabla_mamposteria_entrepisos()):
            print(f"\n{t.titulo}")
            anchos = [max(len(str(x)) for x in [c, *(f[j] for f in t.filas)]) for j, c in enumerate(t.columnas)]
            anchos = [min(a, 40) for a in anchos]
            print("  " + "  ".join(f"{c:<{a}}" for c, a in zip(t.columnas, anchos)))
            for f in t.filas:
                print("  " + "  ".join(f"{str(x)[:a]:<{a}}" for x, a in zip(f, anchos)))
        malas = [(w.muro, c) for w in r.muros for c in w.comprobaciones if args.detalle or not c.cumple]
        if malas:
            print("\nRevisiones" + ("" if args.detalle else " que no cumplen") + ":")
            for muro, c in malas:
                val = "" if c.demanda is None else f": {c.demanda:.3g} contra {c.capacidad:.3g} {c.unidad}"
                print(f"  {muro:<6} {c.concepto} ({c.articulo}){val}. {c.detalle}")
        for a in r.avisos:
            print(f"Aviso: {a}")
        return 0 if r.cumple else 1
    elif args.orden == "reporte":
        from .reporte import Opciones, generar

        op = Opciones(
            motor=args.motor, n_modos=args.modos, metodo=args.metodo, sistema=args.sistema,
            deriva_limite=args.deriva_limite, factor_deriva=args.factor_deriva, autor=args.autor,
            norma=args.norma, grupo=args.grupo, zona=args.zona, periodo_sitio=args.ts, sobrerresistencia=args.sobrerresistencia,
            cortante_minimo=args.cortante_minimo, escalar_desplazamientos=args.escalar_desplazamientos,
            torsion=not args.sin_torsion, excentricidad=args.excentricidad,
            divisor_servicio=args.divisor_servicio, limite_servicio=args.limite_servicio,
        )
        secciones = [x.strip() for x in args.secciones.split(",")] if args.secciones else None
        ruta = generar(modelo, args.salida, op, secciones)
        print(f"Reporte guardado en {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
