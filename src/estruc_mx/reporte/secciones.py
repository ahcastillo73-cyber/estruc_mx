"""Secciones del reporte. Cada una recibe los datos y devuelve una lista de bloques.

Para añadir una sección: escribir una función `(DatosReporte) -> list[Bloque]` y
registrarla en `SECCIONES`. El orden del diccionario es el orden del reporte.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Callable

from ..modelo.masas import G
from ..motores.comun import combinaciones_efectivas
from ..normas.ntc_sismo import MASA_PARTICIPANTE_MINIMA
from . import figuras
from .formulas import tabla_formulas
from .bloques import Bloque, Figura, Lista, Parrafo, Tabla, Titulo
from .datos import DatosReporte

Seccion = Callable[[DatosReporte], list[Bloque]]


def _f(v: float, dec: int = 2) -> str:
    return f"{v:,.{dec}f}"


def _niveles(d: DatosReporte) -> list[float]:
    return sorted({round(n.z, 6) for n in d.modelo.nodos})


# --- 1. Modelo -----------------------------------------------------------------
def modelo(d: DatosReporte) -> list[Bloque]:
    m = d.modelo
    niveles = _niveles(d)
    tipos = Counter(b.tipo for b in m.barras)
    peso = sum(d.masas.values()) * G
    b: list[Bloque] = [Titulo("Descripción del modelo")]
    b.append(Tabla(
        ["Concepto", "Valor"],
        [
            ["Nodos", str(len(m.nodos))],
            ["Barras", ", ".join(f"{n} {t}s" for t, n in sorted(tipos.items())) or "0"],
            *([["Muros y losas", f"{sum(a.tipo == 'muro' for a in m.areas)} muros, {sum(a.tipo == 'losa' for a in m.areas)} losas"],
               ["Malla de muros y losas", f"elementos de {m.tamano_malla:g} m o menos"]] if m.areas else []),
            ["Nodos con apoyo", str(len(m.apoyos))],
            ["Niveles sobre la base", str(max(len(niveles) - 1, 0))],
            ["Altura total (m)", _f(niveles[-1] - niveles[0]) if niveles else "-"],
            ["Peso sísmico W (kN)", _f(peso, 1) if d.masas else "-"],
            ["Masa total (t)", _f(peso / G, 2) if d.masas else "-"],
        ],
        titulo="Datos generales",
        anchos=[0.45, 0.55],
        texto={0, 1},
    ))
    png, _ = figuras.deformada(m, titulo=m.nombre)
    leyenda = "Geometría del modelo (columnas en azul, vigas en verde"
    leyenda += ", muros en ocre y losas en azul claro)" if m.areas else ")"
    b.append(Figura(png, leyenda, ancho=0.7))

    b.append(Titulo("Materiales", 2))
    b.append(Tabla(
        ["Material", "Tipo", "E (MPa)", "ν", "γ (kN/m³)"],
        [[x.nombre, x.tipo, _f(x.E / 1000, 0), _f(x.nu, 2), _f(x.peso_vol, 1)] for x in m.materiales],
        titulo="Materiales",
        texto={0, 1},
    ))
    b.append(Titulo("Secciones", 2))
    filas = []
    for s in m.secciones:
        dims = f"{s.b * 100:.0f} × {s.h * 100:.0f} cm" if s.forma == "rectangular" else "general"
        filas.append([s.nombre, s.material, dims, f"{s.A:.4f}", f"{s.I33:.3e}", f"{s.I22:.3e}", f"{s.J:.3e}"])
    b.append(Tabla(
        ["Sección", "Material", "b × h", "A (m²)", "I33 (m⁴)", "I22 (m⁴)", "J (m⁴)"],
        filas, titulo="Secciones", texto={0, 1, 2},
    ))
    if m.secciones_area and m.areas:
        b.append(Titulo("Secciones de muro y losa", 2))
        usos = Counter(a.seccion for a in m.areas)
        b.append(Tabla(
            ["Sección", "Tipo", "Material", "Espesor (cm)", "Mod. rigidez", "Mod. cortante", "G (MPa)", "Áreas"],
            [[s.nombre, s.tipo, s.material, _f(s.espesor * 100, 1), _f(s.mod_rigidez, 2), _f(s.mod_cortante, 2),
              _f(m.modulos_area(s)[2] / 1000, 0), str(usos.get(s.nombre, 0))]
             for s in m.secciones_area],
            titulo="Secciones de muro y losa", texto={0, 1, 2},
        ))
        b.append(Parrafo(
            "Muros y losas se analizan como cáscaras elásticas (membrana más placa) divididas en elementos "
            "de cuatro nodos. El módulo de cortante en el plano es G = E/(2(1 + ν)), salvo en mampostería, "
            "donde es Gm = 0.2·Em (NTC Mampostería 2023, ec. 2.8.6.4.1) multiplicado por el modificador de "
            "cortante de la sección (0.5 en muros agrietados, 3.1.1.2.3): los motores usan entonces un material "
            "ortótropo con ese G en el plano.", "nota",
        ))
        if any(x.tipo == "mamposteria" for x in m.materiales):
            b.append(tabla_formulas(["mam_em", "mam_gm"]))
    if m.diafragmas:
        from ..modelo.malla import discretizar

        diaf = discretizar(m).diafragmas
        b.append(Titulo("Diafragmas rígidos", 2))
        b.append(Tabla(
            ["Diafragma", "Z (m)", "Masa (t)", "X CM (m)", "Y CM (m)", "Nodos"],
            [[x.nombre, _f(x.z), _f(x.masa), _f(float(x.centro[0]), 3), _f(float(x.centro[1]), 3), str(len(x.esclavos))] for x in diaf],
            titulo="Diafragmas rígidos y centros de masa", texto={0},
        ))
        b.append(Parrafo(
            "En cada diafragma todos los nodos del nivel se mueven como cuerpo rígido en su plano "
            "(X, Y y giro alrededor de Z), con el nodo maestro en el centro de masa. La flexión de las "
            "losas fuera de su plano no cambia.", "nota",
        ))
    return b


# --- 2. Cargas -----------------------------------------------------------------
def cargas(d: DatosReporte) -> list[Bloque]:
    m = d.modelo
    b: list[Bloque] = [Titulo("Cargas y combinaciones")]
    filas = []
    for p in m.patrones:
        F = [0.0, 0.0, 0.0]
        nn = nd = 0
        for c in m.cargas_nodales:
            if c.patron == p.nombre:
                nn += 1
                for k in range(3):
                    F[k] += c.fuerzas[k]
        for c in m.cargas_distribuidas:
            if c.patron == p.nombre:
                nd += 1
                F["XYZ".index(c.direccion)] += c.w * m.longitud(m.barra(c.barra))
        if p.peso_propio:
            from ..modelo.malla import discretizar
            from ..modelo.masas import pesos_propios

            F[2] -= p.peso_propio * sum(pesos_propios(m, discretizar(m)).values())
        na = 0
        for c in m.cargas_area:
            if c.patron == p.nombre:
                na += 1
                F["XYZ".index(c.direccion)] += c.w * m.superficie(m.area(c.area))
        tipo = p.tipo + (f" + {p.peso_propio:g}×peso propio" if p.peso_propio else "")
        filas.append([p.nombre, tipo, str(nn), str(nd), *([str(na)] if m.areas else []), _f(F[0], 1), _f(F[1], 1), _f(F[2], 1)])
    b.append(Tabla(
        ["Patrón", "Tipo", "Cargas nodales", "Cargas en barras", *(["Cargas en áreas"] if m.areas else []),
         "ΣFX (kN)", "ΣFY (kN)", "ΣFZ (kN)"],
        filas, titulo="Patrones de carga y resultantes", texto={0, 1},
    ))
    combos = combinaciones_efectivas(m)
    b.append(Tabla(
        ["Combinación", "Factores"],
        [[c.nombre, " + ".join(f"{f:g}·{p}" for p, f in c.factores.items())] for c in combos],
        titulo="Combinaciones de carga", anchos=[0.3, 0.7], texto={0, 1},
    ))
    b.append(Titulo("Fuente de masa", 2))
    partes = [f"{f:g} × {p}" for p, f in m.fuente_masa.items()]
    if m.peso_propio_en_masa:
        partes.append("peso propio de las barras" + (", muros y losas" if m.areas else ""))
    if m.masas_nodales:
        partes.append(f"{len(m.masas_nodales)} masas nodales explícitas")
    b.append(Parrafo(
        "La masa para el análisis dinámico se obtiene de: " + (", ".join(partes) or "nada") + ". "
        "Las cargas en barras se reparten mitad a cada extremo"
        + ("; las de muros y losas, a los nodos de su malla" if m.areas else "")
        + "; solo se considera masa traslacional."
    ))
    return b


# --- 3. Espectro ---------------------------------------------------------------
def espectro(d: DatosReporte) -> list[Bloque]:
    e = d.modelo.espectro
    b: list[Bloque] = [Titulo("Espectro de diseño")]
    if e is None:
        return b + [Parrafo("El modelo no tiene espectro definido.", "aviso")]
    if e.tipo == "ntc":
        b.append(Parrafo(
            f"Espectro «{e.nombre}» con la forma paramétrica de la NTC Sismo 2023 (3.1.2). "
            "Los parámetros deben ser los del SASID para el sitio."
        ))
        filas = [["a0 (g)", _f(e.a0, 3)], ["c (g)", _f(e.c, 3)], ["Ta (s)", _f(e.Ta, 3)],
                 ["Tb (s)", _f(e.Tb, 3)], ["k", _f(e.k, 3)], ["β", _f(e.beta, 3)]]
    else:
        b.append(Parrafo(f"Espectro tabular «{e.nombre}» con {len(e.T)} puntos, interpolado linealmente."))
        filas = [["T mín – T máx (s)", f"{e.T[0]:g} – {e.T[-1]:g}"], ["Sa máx (g)", _f(max(e.Sa), 3)]]
    filas.append(["Reducción (Q′·R)", _f(e.reduccion, 3)])
    b.append(Tabla(["Parámetro", "Valor"], filas, titulo="Parámetros del espectro", anchos=[0.5, 0.5]))
    periodos = d.propiedades.periodos if d.propiedades else None
    b.append(Figura(figuras.espectro(d.modelo, periodos), "Espectro de diseño y periodos de los modos", 0.85))
    b.append(tabla_formulas(["sa", "p", "reduccion"]))
    return b


# --- 4. Modal ------------------------------------------------------------------
def modal(d: DatosReporte) -> list[Bloque]:
    b: list[Bloque] = [Titulo("Análisis modal")]
    p = d.propiedades
    if p is None:
        return b + [Parrafo("No se hizo análisis modal: " + " ".join(d.avisos), "aviso")]
    ax, ay = p.fraccion_acumulada("X"), p.fraccion_acumulada("Y")
    b.append(Parrafo(
        f"{len(p.periodos)} modos calculados con {d.modos.motor}. Masa total {p.masa_total:,.2f} t."
    ))
    filas = []
    for i, T in enumerate(p.periodos):
        fx, fy, fz = (p.fraccion_masa[k][i] * 100 for k in "XYZ")
        filas.append([str(i + 1), f"{T:.3f}", _f(fx, 1), _f(fy, 1), _f(fz, 1), _f(ax[i] * 100, 1), _f(ay[i] * 100, 1)])
    b.append(Tabla(
        ["Modo", "T (s)", "%Mx", "%My", "%Mz", "Σ%Mx", "Σ%My"],
        filas, titulo="Periodos y participación de masa",
    ))
    minimo = MASA_PARTICIPANTE_MINIMA * 100
    for k, acum in (("X", ax), ("Y", ay)):
        total = acum[-1] * 100 if acum else 0.0
        if total >= minimo:
            n = next(i for i, v in enumerate(acum) if v * 100 >= minimo) + 1
            b.append(Parrafo(f"Dirección {k}: {total:.1f} % de la masa con {len(acum)} modos; "
                             f"se alcanza el {minimo:.0f} % con {n} modos. Cumple."))
        else:
            b.append(Parrafo(f"Dirección {k}: solo {total:.1f} % de la masa participa; las NTC piden al "
                             f"menos {minimo:.0f} %. Aumentar el número de modos.", "aviso"))
    b.append(tabla_formulas(["peso_efectivo", "srss", "cqc", "rho"]))
    return b


# --- 5. Cortante basal ---------------------------------------------------------
def cortante(d: DatosReporte) -> list[Bloque]:
    b: list[Bloque] = [Titulo("Cortante basal")]
    if not d.espectral:
        return b + [Parrafo("No se hizo análisis espectral: " + " ".join(d.avisos), "aviso")]
    W = sum(d.masas.values()) * G
    filas = []
    for k, r in d.espectral.items():
        filas.append([k, r.metodo, _f(r.cortante_basal, 1), _f(W, 1), _f(r.cortante_basal / W, 4)])
    b.append(Tabla(
        ["Dirección", "Combinación modal", "V (kN)", "W (kN)", "V / W"],
        filas, titulo="Cortante basal del análisis modal espectral", texto={0, 1},
    ))
    rev = d.revision
    if rev is not None:
        b.append(Titulo("Cortante basal mínimo", 2))
        b.append(Parrafo(
            "Si el cortante basal de diseño V0 del análisis modal es menor que el mínimo, las fuerzas de "
            "diseño se multiplican por Vmin/V0. V0 es el cortante calculado por la reducción del espectro "
            f"entre el factor Q·R ({d.factor_deriva:g}). "
            + ("Los desplazamientos también se escalan." if rev.criterios.escalar_desplazamientos
               else "Los desplazamientos no se escalan (NTC 2020, sección 1.7).")
        ))
        filas = [[k, f"{c.T1:.3f}", _f(c.V0, 1), _f(c.V0 / c.W, 4), _f(c.coeficiente, 4), _f(c.Vmin, 1),
                  _f(c.factor, 3)] for k, c in rev.cortante.items()]
        b.append(Tabla(
            ["Dirección", "T1 (s)", "V0 (kN)", "V0 / W", "Mínimo / W", "Vmin (kN)", "Factor"],
            filas, titulo="Revisión del cortante basal mínimo",
        ))
        origenes = sorted({c.origen for c in rev.cortante.values()})
        b.append(Parrafo("Mínimo: " + "; ".join(origenes) + ".", "nota"))
        if any(c.factor > 1 for c in rev.cortante.values()):
            b.append(Parrafo("El cortante modal no alcanza el mínimo: las fuerzas de diseño de este reporte "
                             "(muros, torsión) ya incluyen el factor de escala.", "aviso"))
        if rev.criterios.norma == "NTC":
            b.append(tabla_formulas(["cortante_minimo", "amin"]))
    b.append(Titulo("Cortante por entrepiso", 2))
    dirs = [k for k, r in d.espectral.items() if r.cortantes_entrepiso]
    if dirs:
        zs = [z for z, _ in d.espectral[dirs[0]].cortantes_entrepiso]
        filas = []
        for i, z in enumerate(zs):
            fila = [_f(z, 2)]
            for k in dirs:
                v = d.espectral[k].cortantes_entrepiso[i][1]
                fila += [_f(v, 1)]
                if rev is not None:
                    fila += [_f(v * rev.cortante[k].factor, 1)]
            filas.append(fila)
        enc = ["Nivel (m)"]
        for k in dirs:
            enc += [f"V{k} (kN)"] + ([f"V{k} escalado (kN)"] if rev is not None else [])
        b.append(Tabla(enc, filas, titulo="Cortante de entrepiso del análisis modal (abajo del nivel indicado)"))
    b.append(Titulo("Contribución por modo", 2))
    r0 = next(iter(d.espectral.values()))
    p = r0.propiedades
    filas = []
    validos = [i for i, T in enumerate(p.periodos) if math.isfinite(T) and T > 0]
    for j, i in enumerate(validos):
        fila = [str(i + 1), f"{p.periodos[i]:.3f}", f"{r0.sa[j]:.4f}"]
        for k, r in d.espectral.items():
            fila.append(_f(r.cortante_basal_modal[j], 1))
        filas.append(fila)
    b.append(Tabla(
        ["Modo", "T (s)", "Sa (g)"] + [f"V{k} (kN)" for k in d.espectral],
        filas, titulo="Cortante basal por modo, sin combinar",
    ))
    return b


# --- 6. Torsión ----------------------------------------------------------------
def torsion(d: DatosReporte) -> list[Bloque]:
    rev = d.revision
    if rev is None or not rev.pisos:
        return []
    b: list[Bloque] = [Titulo("Centros de masa y torsión accidental")]
    b.append(Tabla(
        ["Nivel (m)", "Masa (t)", "xCM (m)", "yCM (m)", "bx (m)", "by (m)"],
        [[_f(p.z, 2), _f(p.masa, 2), _f(p.xc, 2), _f(p.yc, 2), _f(p.bx, 2), _f(p.by, 2)] for p in rev.pisos],
        titulo="Centro de masa y dimensiones en planta por nivel",
    ))
    if not rev.torsion:
        return b + [Parrafo("No se consideró la torsión accidental.", "aviso")]
    b.append(Parrafo(
        "La torsión natural ya está en el análisis modal, porque el modelo es tridimensional (en análisis dinámico "
        "es se toma con factor 1). La accidental se aplica como un momento M0 en cada nivel, de modo que el momento "
        "de cada entrepiso sea su cortante por ea, medida perpendicularmente al sismo. Se resuelve como caso "
        "estático y su efecto se suma con el signo más desfavorable al del análisis modal, para el sismo en cada "
        "dirección por separado."
    ))
    for k, b_ in (("X", "by"), ("Y", "bx")):
        filas = [[_f(t.z, 2), _f(t.fraccion, 3), _f(t.e, 2), _f(t.V, 1), _f(t.Ma, 1), _f(t.M0, 1)]
                 for t in rev.torsion[k]]
        b.append(Tabla(
            ["Nivel (m)", f"ea/{b_}", "ea (m)", f"V{k} (kN)", "Ma (kN·m)", "M0 (kN·m)"],
            filas, titulo=f"Torsión accidental, sismo en {k} (sin escalar por cortante mínimo)",
        ))
    b.extend(Parrafo(a, "nota") for a in rev.avisos)
    if rev.criterios.norma == "NTC" and rev.criterios.excentricidad is None:
        b.append(tabla_formulas(["excentricidad_diseno", "ea", "momento_torsion"]))
    return b


# --- 7. Derivas ----------------------------------------------------------------
def _tabla_derivas(niveles, por_comp, factor, limite, titulo) -> tuple[Tabla, float, dict[str, list[float]]]:
    filas, peor = [], 0.0
    curvas: dict[str, list[float]] = {k: [] for k in por_comp}
    con_comb = any(hasattr(x, "gobierna") for t in por_comp.values() for x in t.values())
    for z in niveles:
        fila = [_f(z, 2)]
        vmax = 0.0
        for k, tabla in por_comp.items():
            x = tabla.get(z)
            v = (x.deriva if x else 0.0) * factor
            curvas[k].append(v)
            vmax = max(vmax, v)
            fila += [f"{v:.5f}", (getattr(x, "barra", None) or getattr(x, "elemento", "-")) if x else "-"]
            if con_comb:
                fila.append(getattr(x, "gobierna", "-"))
        peor = max(peor, vmax)
        if limite is not None:
            fila.append("Sí" if vmax <= limite else "NO")
        filas.append(fila)
    enc = ["Nivel (m)"]
    for k in por_comp:
        enc += [f"Δ/h {k}", f"Elemento {k}"] + ([f"Comb. {k}"] if con_comb else [])
    if limite is not None:
        enc.append("Cumple")
    paso = 3 if con_comb else 2
    texto = {0} | {j for i in range(len(por_comp)) for j in range(2 + paso * i, 1 + paso * (i + 1))}
    if limite is not None:
        texto.add(len(enc) - 1)
    return Tabla(enc, filas, titulo=titulo, texto=texto), peor, curvas


def _revision(b: list[Bloque], niveles, por_comp, factor, limite, titulo: str, figura: str) -> None:
    tabla, peor, curvas = _tabla_derivas(niveles, por_comp, factor, limite, titulo)
    b.append(tabla)
    if limite is not None:
        b.append(Parrafo(
            f"Distorsión máxima {peor:.5f} contra límite {limite:g}: " + ("cumple." if peor <= limite else "NO cumple."),
            "normal" if peor <= limite else "aviso",
        ))
    b.append(Figura(figuras.derivas(niveles, curvas, limite), figura, 0.6))


def derivas(d: DatosReporte) -> list[Bloque]:
    b: list[Bloque] = [Titulo("Distorsiones de entrepiso")]
    if not d.espectral:
        return b + [Parrafo("No se hizo análisis espectral: " + " ".join(d.avisos), "aviso")]
    limite, origen = d.opciones.limite()
    f = d.factor_deriva
    rev = d.revision
    muros = any(a.tipo == "muro" for a in d.modelo.areas)
    b.append(Titulo("Seguridad de Vida", 2))
    texto = ("Distorsión máxima por entrepiso entre las columnas"
             + (" y los bordes verticales de los muros" if muros else "") + ", del análisis modal espectral")
    if rev is not None:
        texto += (", más la torsión accidental"
                  if rev.torsion else "") + f", combinando 100 % de un sismo con {rev.criterios.ortogonal * 100:.0f} % del otro"
        por_comp = {k: {x.nivel: x for x in v} for k, v in rev.derivas.items()}
    else:
        por_comp = {k: {x.nivel: x for x in r.derivas} for k, r in d.espectral.items()}
    b.append(Parrafo(texto + f". Para compararla con γSV se multiplica por {f:g} (Q·R′; por defecto la "
                     "reducción del espectro)."))
    if limite is None:
        b.append(Parrafo("No se indicó sistema estructural ni límite; la tabla no verifica el cumplimiento. "
                         "Usar --sistema o --deriva-limite.", "aviso"))
    else:
        b.append(Parrafo(f"Límite {limite:g}, {origen}."))
    niveles = sorted({z for t in por_comp.values() for z in t})
    _revision(b, niveles, por_comp, f, limite, "Distorsiones para Seguridad de Vida (ya multiplicadas por Q·R′)",
              "Perfil de distorsiones para Seguridad de Vida")
    claves = ["distorsion", "ortogonal", "seguridad_vida"]

    if rev is not None and d.opciones.grupo == "A":
        b.append(Titulo("Ocupación Inmediata (Grupo A)", 2))
        lim_oi, origen_oi = d.opciones.limite_oi()
        b.append(Parrafo("Distorsiones con el espectro elástico (Q = 1): las calculadas por la reducción del "
                         "espectro, con la misma torsión y combinación de componentes."
                         + (f" Límite {lim_oi:g}, {origen_oi}." if lim_oi is not None else "")))
        if d.opciones.sistema and lim_oi is None:
            b.append(Parrafo("Las NTC no dan γOI para este sistema.", "aviso"))
        por_e = {k: {x.nivel: x for x in v} for k, v in rev.derivas_elasticas.items()}
        _revision(b, niveles, por_e, 1.0, lim_oi, "Distorsiones para Ocupación Inmediata",
                  "Perfil de distorsiones para Ocupación Inmediata")
        claves.append("ocupacion_inmediata")
    elif rev is not None:
        b.append(Titulo("Limitación de Daño No Estructural (Grupo B)", 2))
        if not rev.derivas_servicio:
            b.append(Parrafo(
                "No se revisó: falta la zona sísmica (--zona, y --ts en la zona B) para calcular Ks, o un "
                "espectro de servicio en el modelo (espectro_servicio).", "aviso"))
        else:
            lim_s = rev.criterios.limite_servicio
            b.append(Parrafo(f"Distorsiones con el {rev.origen_servicio}, con la misma torsión y combinación de "
                             f"componentes. Límite {lim_s:g} (0.002 con elementos no estructurales ligados a la "
                             "estructura, 0.004 si están separados o soportan deformaciones apreciables)."))
            por_s = {k: {x.nivel: x for x in v} for k, v in rev.derivas_servicio.items()}
            _revision(b, niveles, por_s, 1.0, lim_s, "Distorsiones para Limitación de Daño",
                      "Perfil de distorsiones para Limitación de Daño")
            claves += ["limitacion_dano", "ks"]
    b.append(tabla_formulas(claves))
    return b


# --- 8. Deformadas -------------------------------------------------------------
MAX_COMBINACIONES = 6
MAX_MODOS = 3


def deformadas(d: DatosReporte) -> list[Bloque]:
    b: list[Bloque] = [Titulo("Desplazamientos y deformadas")]
    r = d.estatico
    if r is not None:
        b.append(Titulo("Análisis estático", 2))
        filas = []
        for combo in r.combinaciones:
            fila = [combo]
            for gdl in range(3):
                nodo, val = r.desplazamiento_maximo(combo, gdl)
                fila += [_f(val * 1000, 2), nodo]
            filas.append(fila)
        b.append(Tabla(
            ["Combinación", "UX (mm)", "Nodo", "UY (mm)", "Nodo", "UZ (mm)", "Nodo"],
            filas, titulo=f"Desplazamiento máximo por combinación ({r.motor})", texto={0, 2, 4, 6},
        ))
        for combo in r.combinaciones[:MAX_COMBINACIONES]:
            png, esc = figuras.deformada(d.modelo, r.desplazamientos[combo], combo)
            b.append(Figura(png, f"Deformada, {combo} (escala ×{esc:.0f})", 0.6))
        if len(r.combinaciones) > MAX_COMBINACIONES:
            b.append(Parrafo(f"Se muestran las primeras {MAX_COMBINACIONES} combinaciones.", "nota"))
    if d.modos is not None:
        b.append(Titulo("Formas modales", 2))
        for i, (T, forma) in enumerate(zip(d.modos.periodos[:MAX_MODOS], d.modos.formas)):
            png, _ = figuras.deformada(d.modelo, forma, f"Modo {i + 1}, T = {T:.3f} s")
            b.append(Figura(png, f"Forma del modo {i + 1} (T = {T:.3f} s)", 0.6))
    return b


# --- 9. Muros y losas ----------------------------------------------------------
_ENC_MURO = ["Muro", "Base (m)", "L (m)", "P (kN)", "V (kN)", "M (kN·m)", "V fuera (kN)", "M fuera (kN·m)"]


def muros_losas(d: DatosReporte) -> list[Bloque]:
    from ..analisis.areas import COMPONENTES_MURO, bases_muros, esfuerzos_areas, extremos_esfuerzos, todas_fuerzas_muros
    from ..modelo.malla import discretizar

    m = d.modelo
    if not m.areas:
        return []
    malla = discretizar(m)
    bases = bases_muros(m, malla)
    b: list[Bloque] = [Titulo("Muros y losas")]
    b.append(Parrafo(
        f"{len(malla.elementos)} elementos de cáscara y {len(malla.nodos)} nodos en la malla de análisis. "
        "Fuerzas en la base de cada muro: P axial (positiva en tensión), V y M en el plano del muro, "
        "y V y M fuera del plano, en los ejes del muro (1 horizontal a lo largo, 2 vertical)."
    ))
    r = d.estatico
    if bases and r is not None:
        b.append(Titulo("Fuerzas en muros, análisis estático", 2))
        for combo in r.combinaciones[:MAX_COMBINACIONES]:
            f = todas_fuerzas_muros(m, malla, r.fuerzas_elementos.get(combo, {}))
            filas = [[a, _f(x.elevacion, 2), _f(x.longitud, 2), *(_f(f[a][c], 1) for c in COMPONENTES_MURO[:5])]
                     for a, x in bases.items()]
            b.append(Tabla(_ENC_MURO, filas, titulo=f"Fuerzas en la base de los muros, {combo}"))
        if len(r.combinaciones) > MAX_COMBINACIONES:
            b.append(Parrafo(f"Se muestran las primeras {MAX_COMBINACIONES} combinaciones.", "nota"))
    if bases and d.espectral:
        b.append(Titulo("Fuerzas en muros, análisis modal espectral", 2))
        for k, re_ in d.espectral.items():
            if not re_.fuerzas_muros:
                continue
            filas = [[a, _f(x.elevacion, 2), _f(x.longitud, 2), *(_f(re_.fuerzas_muros[a][c], 1) for c in COMPONENTES_MURO[:5])]
                     for a, x in bases.items()]
            b.append(Tabla(_ENC_MURO, filas, titulo=f"Fuerzas en muros, sismo en {k} ({re_.metodo}, máximos sin signo)"))
    rev = d.revision
    if bases and rev is not None and rev.fuerzas_muros:
        b.append(Titulo("Fuerzas sísmicas de diseño en muros", 2))
        b.append(Parrafo(
            "Envolvente de 100 % de un sismo más " f"{rev.criterios.ortogonal * 100:.0f} % del perpendicular, con "
            "la torsión accidental sumada con el signo más desfavorable y el factor de cortante mínimo. Son "
            "valores sin signo, solo de sismo: para el diseño se combinan con las cargas de gravedad."
        ))
        filas = [[a, _f(x.elevacion, 2), _f(x.longitud, 2), *(_f(rev.fuerzas_muros[a][c], 1) for c in COMPONENTES_MURO[:5])]
                 for a, x in bases.items() if a in rev.fuerzas_muros]
        b.append(Tabla(_ENC_MURO, filas, titulo="Fuerzas sísmicas de diseño en la base de los muros"))
    losas = [a for a in m.areas if a.tipo == "losa"]
    if losas and r is not None:
        b.append(Titulo("Momentos en losas", 2))
        b.append(Parrafo(
            "Momentos por unidad de ancho al centro de los elementos, en los ejes de cada losa (1 = X, 2 = Y en "
            "losas horizontales). Positivo: tensión en la cara inferior. Los valores dependen del tamaño de malla.",
            "nota",
        ))
        for combo in r.combinaciones[:MAX_COMBINACIONES]:
            esf = esfuerzos_areas(m, malla, r.desplazamientos[combo])
            filas = []
            for a in losas:
                e = extremos_esfuerzos(esf[a.id])
                filas.append([a.id, a.seccion, *(_f(v, 2) for v in (*e["M11"], *e["M22"])),
                              _f(max(abs(v) for v in e["M12"]), 2)])
            b.append(Tabla(
                ["Losa", "Sección", "M11 mín", "M11 máx", "M22 mín", "M22 máx", "|M12| máx"],
                filas, titulo=f"Momentos en losas (kN·m/m), {combo}", texto={0, 1},
            ))
    return b


# --- 10. Mampostería ----------------------------------------------------------
_PIEZAS = {
    "tabique_arcilla_artesanal": "tabique de arcilla artesanal", "tabique_arcilla_extruido": "tabique de arcilla extruido",
    "bloque_concreto": "bloque de concreto", "tabicon_concreto": "tabicón de concreto", "otra_arcilla": "otra (arcilla)",
    "otra_concreto": "otra (concreto)",
}
_MODALIDAD = {"confinada": "confinada", "reforzada_interior": "reforzada interiormente", "no_reforzada": "no reforzada"}


def _estado(ok: bool) -> str:
    return "sí" if ok else "NO"


def mamposteria(d: DatosReporte) -> list[Bloque]:
    from ..diseno.mamposteria import propiedades
    from ..normas.ntc_mamposteria import modulo_elasticidad
    from ..normas.ntc_sismo import DISTORSIONES_LIMITE

    r = d.mamposteria
    if r is None or not r.muros:
        return []
    m = d.modelo
    b: list[Bloque] = [Titulo("Revisión de muros de mampostería")]
    b.append(Parrafo(
        "Revisión de cada muro según la NTC para Diseño y Construcción de Estructuras de Mampostería 2023 "
        "(estructuras Tipo I). Las fuerzas son las del muro junto con sus castillos, en su base: los castillos "
        "se modelan como barras en su eje (3.2.2.4) y un castillo compartido por varios muros del nivel se reparte "
        "por partes iguales. La carga vertical se revisa con las combinaciones de gravedad factorizadas ("
        + ", ".join(f"«{c}»" for c in r.combinaciones_gravedad) + "). "
        + (f"El cortante y la flexocompresión se revisan con las fuerzas sísmicas de diseño (cortante mínimo, "
           f"torsión accidental y 100 % + 30 %) por FC = {r.criterios.fc_accidental:g}, más la gravedad de "
           f"«{r.combinacion_sismo}» ({' + '.join(f'{v:g}·{k}' for k, v in r.factores_sismo.items())})."
           if r.con_sismo else "No hay revisión sísmica: el cortante no se revisó.")
    ))
    # --- materiales y refuerzo ---
    b.append(Titulo("Materiales y refuerzo", 2))
    filas = []
    for nombre in sorted({w.material for w in r.muros}):
        p, supuesto = propiedades(m, nombre)
        mat = m.material(nombre)
        filas.append([
            nombre + (" (supuesto)" if supuesto else ""), _PIEZAS[p.pieza] + (", hueca" if p.hueca else ", maciza"),
            p.mortero, _f(p.fm / 1000, 2), _f(p.vm / 1000, 2), _f(mat.E / 1000, 0),
            _f(modulo_elasticidad(p.fm, p.de_concreto) / 1000, 0), _f(mat.G / 1000, 0),
        ])
    b.append(Tabla(["Material", "Pieza", "Mortero", "f'm (MPa)", "v'm (MPa)", "E modelo (MPa)", "Em de 2.8.5.4 (MPa)",
                    "Gm (MPa)"], filas, titulo="Propiedades de diseño de la mampostería", texto={0, 1, 2}))
    filas = []
    for nombre in sorted({w.seccion for w in r.muros}):
        s = m.seccion_area(nombre)
        x = s.mamposteria
        if x is None:
            filas.append([nombre, "confinada (supuesta)", "15 × 15", "4 #3 (2.85)", "-", "-", "-"])
            continue
        filas.append([
            nombre, _MODALIDAD[x.modalidad], f"{x.castillo_b * 100:.0f} × {x.castillo_h * 100:.0f}",
            f"{x.castillo_barras} barras ({x.castillo_As * 1e4:.2f})",
            f"{x.estribo_Asc * 1e4:.2f} @ {x.estribo_s * 100:.0f} ({x.estribo_s_extremo * 100:.1f})",
            f"{x.dala_b * 100:.0f} × {x.dala_h * 100:.0f}",
            "-" if x.ph_fyh(s.espesor) <= 0 else f"{x.Ash * 1e4:.2f} cm² @ {x.sh * 100:.0f} cm "
                                                  f"(ph·fyh = {x.ph_fyh(s.espesor) / 1000:.2f} MPa)",
        ])
    b.append(Tabla(["Sección", "Modalidad", "Castillo (cm)", "As castillo (cm²)", "Estribos Asc (cm²) @ s (extremos), cm",
                    "Dala (cm)", "Refuerzo horizontal"], filas, titulo="Refuerzo de los muros",
                   texto={0, 1, 2, 3, 4, 5, 6}))
    # --- resistencias ---
    b.append(Titulo("Resistencias", 2))
    b.append(tabla_formulas(["mam_pr", "mam_fe", "mam_fe_ec", "mam_vr", "mam_vmr", "mam_f", "mam_vsr", "mam_eta",
                             "mam_k0k1", "mam_mr", "mam_mr_tension", "mam_fc"],
                            "Fórmulas de referencia, resistencias de muros"))
    filas = []
    for w in r.muros:
        filas.append([
            w.muro, _f(w.z, 2), w.direccion, _f(w.L, 2), _f(w.t * 100, 0), _f(w.FE, 2), _f(w.Pu, 1), _f(w.PR, 1),
            "-" if w.Vu is None else _f(w.Vu, 1), "-" if w.Vu is None else _f(w.VR, 1),
            "-" if w.Mu is None else _f(w.Mu, 1), "-" if w.MR is None else _f(w.MR, 1), _f(w.relacion, 2),
            _estado(all(c.cumple for c in w.comprobaciones if c.resistencia)),
        ])
    b.append(Tabla(["Muro", "Base (m)", "Dir.", "L (m)", "t (cm)", "FE", "Pu (kN)", "PR (kN)", "Vu (kN)", "VR (kN)",
                    "Mu (kN·m)", "MR (kN·m)", "D/C", "Cumple"], filas,
                   titulo="Carga vertical, cortante y flexocompresión en el plano", texto={0, 2, 13}))
    filas = [[w.muro, _f(w.P_cortante or 0, 1), _f(w.f, 3), _f(w.VmR, 1), _f(w.ph_fyh / 1000, 2), _f(w.eta, 3),
              _f(w.VsR, 1)] for w in r.muros if w.Vu is not None]
    if filas:
        b.append(Tabla(["Muro", "P (kN)", "f", "VmR (kN)", "ph·fyh (MPa)", "η", "VsR (kN)"], filas,
                       titulo="Detalle del cortante resistente"))
    # --- requisitos ---
    b.append(Titulo("Requisitos de castillos, dalas y refuerzo", 2))
    b.append(tabla_formulas(["mam_sep", "mam_as", "mam_asc"], "Fórmulas de referencia, requisitos"))
    fallas = [[w.muro, c.concepto, c.articulo, "-" if c.demanda is None else _f(c.demanda, 2),
               "-" if c.capacidad is None else _f(c.capacidad, 2), c.unidad, c.detalle]
              for w in r.muros for c in w.comprobaciones if not c.resistencia and not c.cumple]
    if fallas:
        b.append(Tabla(["Muro", "Requisito", "Artículo", "Valor", "Límite", "Unidad", "Nota"], fallas,
                       titulo="Requisitos que no se cumplen", texto={0, 1, 2, 5, 6}))
    else:
        b.append(Parrafo("Todos los muros cumplen los requisitos de geometría y refuerzo revisados."))
    revisados = sorted({c.concepto for w in r.muros for c in w.comprobaciones if not c.resistencia})
    b.append(Parrafo("Requisitos revisados: " + ", ".join(revisados) + ".", "nota"))
    # --- entrepiso ---
    if r.entrepisos:
        b.append(Titulo("Cortante resistente de entrepiso", 2))
        b.append(tabla_formulas(["mam_entrepiso"]))
        b.append(Tabla(
            ["Dirección", "Entrepiso (m)", "Muros", "ΣAT (m²)", "σ (kPa)", "VR (kN)", "0.8·Vu (kN)", "Cumple"],
            [[e.direccion, f"{e.z_base:g} a {e.z_tope:g}", str(len(e.muros)), _f(e.AT, 3), _f(e.sigma, 1), _f(e.VR, 1),
              _f(0.8 * e.Vu, 1), _estado(e.cumple)] for e in r.entrepisos],
            titulo="Revisión del cortante de entrepiso", texto={0, 1, 7},
        ))
    # --- conclusión ---
    desc = DISTORSIONES_LIMITE[r.sistema][0]
    malos = [w.muro for w in r.muros if not w.cumple]
    b.append(Parrafo(
        f"Sistema: {desc[0].lower() + desc[1:]}; Q = {r.Q:g} (4.1.13 y NTC Sismo, tabla 4.3.3"
        + (", reducido en 0.5 por tener más de seis niveles" if r.niveles > 6 else "") + "). "
        + ("Todos los muros y entrepisos cumplen." if r.cumple else
           f"No cumplen {len(malos)} de {len(r.muros)} muros: {', '.join(malos)}."
           + ("" if all(e.cumple for e in r.entrepisos) else " Hay entrepisos que no cumplen."))
    , "normal" if r.cumple else "aviso"))
    avisos = list(r.avisos) + sorted({a for w in r.muros for a in w.avisos})
    b.extend(Parrafo(a, "nota") for a in avisos)
    return b


# --- Avisos --------------------------------------------------------------------
def notas(d: DatosReporte) -> list[Bloque]:
    elementos = list(d.avisos) + [
        "Prueba de concepto (fase 0): revisar los resultados con un cálculo independiente antes de usarlos.",
    ]
    if d.revision is not None:
        elementos.append(
            "Revisión sísmica con la NTC Sismo 2023 (1.7, 2.3, 2.5, 3.1, 4.3 y 7.5). Q·R′ es el factor de las "
            "distorsiones; si Q′ ≠ Q (periodos cortos) indicarlo con --factor-deriva. No se aplican el incremento "
            "de γ para muros esbeltos ni la reducción para mampostería de más de 6 niveles (tablas 4.3)."
            + (" Los valores de CFE se tomaron de memoria y no se han verificado." if d.revision.criterios.norma == "CFE" else "")
        )
    if d.modelo.areas:
        elementos.append(
            "Muros y losas: los dos motores usan elementos de cáscara distintos (PyNite DKMQ, OpenSees ShellMITC4) "
            "sobre la misma malla; con malla de 0.5 m sus resultados difieren menos de 3 %. No hay diafragma rígido: "
            "las losas aportan su rigidez en su plano."
        )
    return [Titulo("Notas y limitaciones"), Lista(elementos)]


SECCIONES: dict[str, Seccion] = {
    "modelo": modelo,
    "cargas": cargas,
    "espectro": espectro,
    "modal": modal,
    "cortante": cortante,
    "torsion": torsion,
    "derivas": derivas,
    "deformadas": deformadas,
    "muros": muros_losas,
    "mamposteria": mamposteria,
    "notas": notas,
}
