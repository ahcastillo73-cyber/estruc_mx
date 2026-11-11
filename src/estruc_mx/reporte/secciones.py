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
            ["Sección", "Tipo", "Material", "Espesor (cm)", "Mod. rigidez", "Áreas"],
            [[s.nombre, s.tipo, s.material, _f(s.espesor * 100, 1), _f(s.mod_rigidez, 2), str(usos.get(s.nombre, 0))]
             for s in m.secciones_area],
            titulo="Secciones de muro y losa", texto={0, 1, 2},
        ))
        b.append(Parrafo(
            "Muros y losas se analizan como cáscaras elásticas (membrana más placa) divididas en elementos "
            "de cuatro nodos. El módulo de cortante es G = E/(2(1 + ν)); para mampostería las NTC indican "
            "G = 0.2·Em, que este modelo isótropo no reproduce.", "nota",
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
            f"Espectro «{e.nombre}» con la forma paramétrica de las NTC Diseño por Sismo. "
            "Verificar los parámetros contra los de SASID para el sitio."
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


# --- 6. Derivas ----------------------------------------------------------------
def derivas(d: DatosReporte) -> list[Bloque]:
    b: list[Bloque] = [Titulo("Distorsiones de entrepiso")]
    if not d.espectral:
        return b + [Parrafo("No se hizo análisis espectral: " + " ".join(d.avisos), "aviso")]
    limite, origen = d.opciones.limite()
    f = d.factor_deriva
    b.append(Parrafo(
        "Distorsión máxima por entrepiso entre las columnas"
        + (" y los bordes verticales de los muros" if any(a.tipo == "muro" for a in d.modelo.areas) else "")
        + ", del análisis modal espectral. "
        f"Para compararla con el límite se multiplica por {f:g} (Q·R; por defecto la reducción del espectro)."
    ))
    if limite is None:
        b.append(Parrafo("No se indicó sistema estructural ni límite; la tabla no verifica el cumplimiento. "
                         "Usar --sistema o --deriva-limite.", "aviso"))
    else:
        b.append(Parrafo(f"Límite {limite:g}, {origen}."))

    niveles = sorted({x.nivel for r in d.espectral.values() for x in r.derivas})
    por_dir = {k: {x.nivel: x for x in r.derivas} for k, r in d.espectral.items()}
    filas, peor = [], 0.0
    for z in niveles:
        fila = [_f(z, 2)]
        for k in d.espectral:
            x = por_dir[k].get(z)
            v = x.deriva * f if x else 0.0
            peor = max(peor, v)
            fila += [f"{v:.5f}", x.barra if x else "-"]
        if limite is not None:
            v_max = max(por_dir[k][z].deriva * f for k in d.espectral if z in por_dir[k])
            fila.append("Sí" if v_max <= limite else "NO")
        filas.append(fila)
    enc = ["Nivel (m)"]
    for k in d.espectral:
        enc += [f"Δ/h {k}", f"Elemento {k}"]
    if limite is not None:
        enc.append("Cumple")
    texto = {0} | {2 + 2 * i for i in range(len(d.espectral))} | ({len(enc) - 1} if limite is not None else set())
    b.append(Tabla(enc, filas, titulo="Distorsiones de entrepiso (ya multiplicadas por el factor)", texto=texto))
    if limite is not None:
        b.append(Parrafo(
            f"Distorsión máxima {peor:.5f} contra límite {limite:g}: " + ("cumple." if peor <= limite else "NO cumple."),
            "normal" if peor <= limite else "aviso",
        ))
    curvas = {k: [por_dir[k][z].deriva * f if z in por_dir[k] else 0.0 for z in niveles] for k in d.espectral}
    b.append(Figura(figuras.derivas(niveles, curvas, limite), "Perfil de distorsiones de entrepiso", 0.6))
    b.append(Parrafo("Falta la revisión de limitación de daños (servicio) de las NTC.", "nota"))
    return b


# --- 7. Deformadas -------------------------------------------------------------
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


# --- 8. Muros y losas ----------------------------------------------------------
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


# --- Avisos --------------------------------------------------------------------
def notas(d: DatosReporte) -> list[Bloque]:
    elementos = list(d.avisos) + [
        "Prueba de concepto (fase 0): revisar los resultados con un cálculo independiente antes de usarlos.",
        "Las distorsiones límite y el espectro paramétrico deben verificarse contra la edición vigente de las NTC.",
    ]
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
    "derivas": derivas,
    "deformadas": deformadas,
    "muros": muros_losas,
    "notas": notas,
}
