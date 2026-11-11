"""Conversión entre las listas del modelo (materiales, secciones, patrones, combinaciones)
y las filas de texto que se editan en las tablas de «Definir». Sin interfaz gráfica."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import get_args

from ..modelo import (
    Combinacion, Edificio, Material, PatronCarga, PropiedadesMamposteria, RefuerzoMuroMamposteria, SeccionArea,
    SeccionGeneral, SeccionRectangular,
)

# Tablas que no son una lista del modelo sino datos adicionales de otra: colección -> la del modelo
COLECCION_DEL_MODELO = {"mamposteria": "materiales", "refuerzo_muros": "secciones_area"}

_SI_NO = ["no", "sí"]
# (atributo, título, factor de unidades del modelo a la tabla)
_CAMPOS_MAMPOSTERIA = [("fan", "fan (An/Ab)", 1.0), ("fp", "f'p (MPa)", 1e-3), ("fm", "f'm (MPa)", 1e-3), ("vm", "v'm (MPa)", 1e-3)]
_CAMPOS_REFUERZO = [
    ("castillo_b", "Castillo b (cm)", 100), ("castillo_h", "Castillo h (cm)", 100), ("castillo_As", "As castillo (cm²)", 1e4),
    ("castillo_barras", "Barras", 1), ("castillo_fy", "fy (MPa)", 1e-3), ("castillo_fc", "f'c (MPa)", 1e-3),
    ("estribo_Asc", "Asc estribo (cm²)", 1e4), ("estribo_s", "s estribos (cm)", 100),
    ("estribo_s_extremo", "s en extremos (cm)", 100), ("dala_b", "Dala b (cm)", 100), ("dala_h", "Dala h (cm)", 100),
    ("Ash", "Ash horizontal (cm²)", 1e4), ("sh", "sh (cm)", 100), ("fyh", "fyh (MPa)", 1e-3),
    ("pv_fyv", "pv·fyv (MPa)", 1e-3), ("fnm", "fnm", 1.0),
]


@dataclass
class Columna:
    titulo: str
    opciones: list[str] = field(default_factory=list)  # vacía = texto libre
    solo_lectura: bool = False


def _opciones(modelo_cls, campo: str) -> list[str]:
    return list(get_args(modelo_cls.model_fields[campo].annotation))


def columnas(coleccion: str, modelo: Edificio) -> list[Columna]:
    if coleccion == "materiales":
        return [Columna("Nombre"), Columna("Tipo", _opciones(Material, "tipo")), Columna("E (kPa)"), Columna("ν"), Columna("Peso vol. (kN/m³)")]
    if coleccion == "secciones":
        return [
            Columna("Nombre"), Columna("Forma", ["rectangular", "general"]),
            Columna("Material", [m.nombre for m in modelo.materiales]),
            Columna("b (m)"), Columna("h (m)"), Columna("A (m²)"), Columna("I33 (m⁴)"), Columna("I22 (m⁴)"), Columna("J (m⁴)"),
        ]
    if coleccion == "secciones_area":
        return [
            Columna("Nombre"), Columna("Tipo", _opciones(SeccionArea, "tipo")),
            Columna("Material", [m.nombre for m in modelo.materiales]), Columna("Espesor (m)"),
            Columna("Mod. rigidez"), Columna("Mod. cortante"),
        ]
    if coleccion == "mamposteria":
        return [
            Columna("Material", [m.nombre for m in modelo.materiales if m.tipo == "mamposteria"]),
            Columna("Pieza", _opciones_campo(PropiedadesMamposteria, "pieza")), Columna("Hueca", _SI_NO),
            Columna(_CAMPOS_MAMPOSTERIA[0][1]), Columna("Mortero", ["I", "II"]),
            *(Columna(t) for _, t, _ in _CAMPOS_MAMPOSTERIA[1:]),
        ]
    if coleccion == "refuerzo_muros":
        return [
            Columna("Sección", [s.nombre for s in modelo.secciones_area if s.tipo == "muro"]),
            Columna("Modalidad", _opciones_campo(RefuerzoMuroMamposteria, "modalidad")),
            *(Columna(t) for _, t, _ in _CAMPOS_REFUERZO),
        ]
    if coleccion == "patrones":
        return [Columna("Nombre"), Columna("Tipo", _opciones(PatronCarga, "tipo")), Columna("Peso propio ×")]
    if coleccion == "combinaciones":
        return [Columna("Nombre"), Columna("Factores (p. ej. 1.3*CM + 1.5*CV)")]
    raise ValueError(f"colección desconocida: {coleccion}")


def _opciones_campo(modelo_cls, campo: str) -> list[str]:
    return list(get_args(modelo_cls.model_fields[campo].annotation))


def _num(v: float) -> str:
    return f"{v:.6g}"


def _num_u(v, factor: float) -> str:
    return "" if v is None else _num(v * factor)


def filas(coleccion: str, modelo: Edificio) -> list[list[str]]:
    """Filas de texto; la primera columna siempre es el nombre (la clave)."""
    if coleccion == "materiales":
        return [[m.nombre, m.tipo, _num(m.E), _num(m.nu), _num(m.peso_vol)] for m in modelo.materiales]
    if coleccion == "secciones":
        out = []
        for s in modelo.secciones:
            if s.forma == "rectangular":
                out.append([s.nombre, s.forma, s.material, _num(s.b), _num(s.h), "", "", "", ""])
            else:
                out.append([s.nombre, s.forma, s.material, "", "", _num(s.A), _num(s.I33), _num(s.I22), _num(s.J)])
        return out
    if coleccion == "secciones_area":
        return [[s.nombre, s.tipo, s.material, _num(s.espesor), _num(s.mod_rigidez), _num(s.mod_cortante)]
                for s in modelo.secciones_area]
    if coleccion == "mamposteria":
        out = []
        for m in modelo.materiales:
            if m.tipo != "mamposteria" or m.mamposteria is None:
                continue
            p = m.mamposteria
            out.append([m.nombre, p.pieza, _SI_NO[p.hueca], _num(p.fan), p.mortero,
                        *(_num_u(getattr(p, a), f) for a, _, f in _CAMPOS_MAMPOSTERIA[1:])])
        return out
    if coleccion == "refuerzo_muros":
        return [[s.nombre, s.mamposteria.modalidad, *(_num_u(getattr(s.mamposteria, a), f) for a, _, f in _CAMPOS_REFUERZO)]
                for s in modelo.secciones_area if s.mamposteria is not None]
    if coleccion == "patrones":
        return [[p.nombre, p.tipo, _num(p.peso_propio)] for p in modelo.patrones]
    if coleccion == "combinaciones":
        return [[c.nombre, formatear_factores(c.factores)] for c in modelo.combinaciones]
    raise ValueError(f"colección desconocida: {coleccion}")


def objetos(coleccion: str, filas_: list[list[str]], previo: Edificio | None = None,
            renombres: dict[str, str] | None = None) -> list:
    """Objetos del modelo a partir de las filas; `ValueError` con el número de fila si algo falla.

    Con `previo` se conservan los datos que la tabla no muestra (las propiedades de mampostería
    de materiales y secciones). Las tablas «mamposteria» y «refuerzo_muros» devuelven la lista
    completa de materiales o de secciones de muro y losa con esos datos cambiados."""
    if coleccion in COLECCION_DEL_MODELO:
        if previo is None:
            raise ValueError("falta el modelo")
        return _objetos_adicionales(coleccion, filas_, previo)
    out = _objetos(coleccion, filas_)
    if previo is not None and coleccion in ("materiales", "secciones_area"):
        antes = {v: k for k, v in (renombres or {}).items()}
        viejos = {x.nombre: x for x in getattr(previo, coleccion)}
        for x in out:
            v = viejos.get(antes.get(x.nombre, x.nombre))
            if v is None:
                continue
            x.mamposteria = v.mamposteria
            if coleccion == "materiales":
                x.G_cortante = v.G_cortante
    return out


def _objetos_adicionales(coleccion: str, filas_: list[list[str]], previo: Edificio) -> list:
    nuevos = {}
    for k, f in enumerate(filas_, start=1):
        f = [c.strip() for c in f]
        try:
            if coleccion == "mamposteria":
                fan = _float(f[3] or "1")
                vals = {a: (_float(x) / fac if x else None) for (a, _, fac), x in zip(_CAMPOS_MAMPOSTERIA[1:], f[5:])}
                if vals["fm"] is None and vals["fp"] is not None:
                    from ..normas.ntc_mamposteria import fm_de_tabla

                    concreto = PropiedadesMamposteria(pieza=f[1], fm=1, vm=1).de_concreto
                    vals["fm"] = fm_de_tabla(vals["fp"] / 1000, f[4], concreto) * 1000
                if vals["fm"] is None or vals["vm"] is None:
                    raise ValueError("faltan f'm (o f'p para tomarla de las tablas 2.8.1.4) y v'm")
                nuevos[f[0]] = PropiedadesMamposteria(pieza=f[1], hueca=f[2] == "sí", fan=fan, mortero=f[4], **vals)
            else:
                vals = {a: _float(x) / fac for (a, _, fac), x in zip(_CAMPOS_REFUERZO, f[2:]) if x}
                if "castillo_barras" in vals:
                    vals["castillo_barras"] = int(round(vals["castillo_barras"]))
                nuevos[f[0]] = RefuerzoMuroMamposteria(modalidad=f[1], **vals)
        except (ValueError, IndexError) as e:
            raise ValueError(f"fila {k}: {_limpio(e)}") from None
    lista = [x.model_copy(deep=True) for x in getattr(previo, COLECCION_DEL_MODELO[coleccion])]
    desconocidos = set(nuevos) - {x.nombre for x in lista}
    if desconocidos:
        raise ValueError(f"no existen: {', '.join(sorted(desconocidos))}")
    for x in lista:
        if coleccion == "mamposteria" and x.tipo != "mamposteria":
            if x.nombre in nuevos:
                raise ValueError(f"«{x.nombre}» no es un material de tipo mampostería")
            continue
        x.mamposteria = nuevos.get(x.nombre)
    return lista


def _objetos(coleccion: str, filas_: list[list[str]]) -> list:
    out = []
    for k, f in enumerate(filas_, start=1):
        f = [c.strip() for c in f]
        try:
            if not f[0]:
                raise ValueError("falta el nombre")
            if coleccion == "materiales":
                out.append(Material(nombre=f[0], tipo=f[1], E=_float(f[2]), nu=_float(f[3]), peso_vol=_float(f[4] or "0")))
            elif coleccion == "secciones":
                if f[1] == "rectangular":
                    out.append(SeccionRectangular(nombre=f[0], material=f[2], b=_float(f[3]), h=_float(f[4])))
                else:
                    out.append(SeccionGeneral(nombre=f[0], material=f[2], A=_float(f[5]), I33=_float(f[6]), I22=_float(f[7]), J=_float(f[8])))
            elif coleccion == "secciones_area":
                mc = f[5] if len(f) > 5 and f[5] else "1"
                out.append(SeccionArea(nombre=f[0], tipo=f[1], material=f[2], espesor=_float(f[3]),
                                       mod_rigidez=_float(f[4] or "1"), mod_cortante=_float(mc)))
            elif coleccion == "patrones":
                pp = f[2] if len(f) > 2 and f[2] else "0"
                out.append(PatronCarga(nombre=f[0], tipo=f[1], peso_propio=_float(pp)))
            elif coleccion == "combinaciones":
                out.append(Combinacion(nombre=f[0], factores=leer_factores(f[1])))
            else:
                raise ValueError(f"colección desconocida: {coleccion}")
        except (ValueError, IndexError) as e:
            raise ValueError(f"fila {k}: {_limpio(e)}") from None
    return out


def formatear_factores(factores: dict[str, float]) -> str:
    return " + ".join(f"{_num(f)}*{p}" for p, f in factores.items())


_TERMINO = re.compile(r"^(?:(?P<f>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*\*\s*)?(?P<p>\S(?:.*\S)?)$")


def leer_factores(texto: str) -> dict[str, float]:
    """«1.3*CM + 1.5*CV» -> {"CM": 1.3, "CV": 1.5}. Un patrón sin factor vale 1."""
    out: dict[str, float] = {}
    for t in texto.split("+"):
        t = t.strip()
        if not t:
            continue
        g = _TERMINO.match(t)
        if not g:
            raise ValueError(f"no se entiende «{t}»")
        out[g["p"]] = out.get(g["p"], 0.0) + float(g["f"] or 1.0)
    if not out:
        raise ValueError("la combinación no tiene factores")
    return out


def leer_lista(texto: str) -> list[float]:
    """«6, 6, 8» o «3x6, 8» -> [6, 6, 6, 8] (como los claros de ETABS)."""
    out: list[float] = []
    for t in re.split(r"[,;\s]+", texto.strip()):
        if not t:
            continue
        if "x" in t.lower():
            n, v = t.lower().split("x", 1)
            out += [_float(v)] * int(n)
        else:
            out.append(_float(t))
    return out


def _float(t: str) -> float:
    try:
        return float(t.replace(",", "."))
    except ValueError:
        raise ValueError(f"«{t}» no es un número") from None


def _limpio(e: Exception) -> str:
    errs = getattr(e, "errors", None)
    if callable(errs):
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in errs())
    return str(e)
