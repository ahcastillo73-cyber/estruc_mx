"""Conversión entre las listas del modelo (materiales, secciones, patrones, combinaciones)
y las filas de texto que se editan en las tablas de «Definir». Sin interfaz gráfica."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import get_args

from ..modelo import Combinacion, Edificio, Material, PatronCarga, SeccionArea, SeccionGeneral, SeccionRectangular


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
            Columna("Mod. rigidez"),
        ]
    if coleccion == "patrones":
        return [Columna("Nombre"), Columna("Tipo", _opciones(PatronCarga, "tipo")), Columna("Peso propio ×")]
    if coleccion == "combinaciones":
        return [Columna("Nombre"), Columna("Factores (p. ej. 1.3*CM + 1.5*CV)")]
    raise ValueError(f"colección desconocida: {coleccion}")


def _num(v: float) -> str:
    return f"{v:.6g}"


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
        return [[s.nombre, s.tipo, s.material, _num(s.espesor), _num(s.mod_rigidez)] for s in modelo.secciones_area]
    if coleccion == "patrones":
        return [[p.nombre, p.tipo, _num(p.peso_propio)] for p in modelo.patrones]
    if coleccion == "combinaciones":
        return [[c.nombre, formatear_factores(c.factores)] for c in modelo.combinaciones]
    raise ValueError(f"colección desconocida: {coleccion}")


def objetos(coleccion: str, filas_: list[list[str]]) -> list:
    """Objetos del modelo a partir de las filas; `ValueError` con el número de fila si algo falla."""
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
                out.append(SeccionArea(nombre=f[0], tipo=f[1], material=f[2], espesor=_float(f[3]), mod_rigidez=_float(f[4] or "1")))
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
