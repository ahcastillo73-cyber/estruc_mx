"""Reporte de análisis por bloques: datos -> secciones -> bloques -> PDF o Word.

    from estruc_mx.reporte import Opciones, generar
    generar(modelo, "reporte.pdf", Opciones(motor="pynite", sistema="marco_concreto_alta"))

- `datos.preparar` corre los análisis.
- `secciones.SECCIONES` convierte los datos en bloques; ahí se añaden secciones nuevas.
- `pdf.py` y `word.py` dibujan los bloques; el formato se elige por la extensión.
"""

from __future__ import annotations

from pathlib import Path

from ..modelo import Edificio
from .bloques import Documento
from .datos import DatosReporte, Opciones, preparar
from .secciones import SECCIONES

FORMATOS = {".pdf": "pdf", ".docx": "word"}


def construir(datos: DatosReporte, secciones: list[str] | None = None) -> Documento:
    nombres = secciones or list(SECCIONES)
    desconocidas = [s for s in nombres if s not in SECCIONES]
    if desconocidas:
        raise ValueError(f"secciones desconocidas {desconocidas}; opciones: {', '.join(SECCIONES)}")
    op = datos.opciones
    doc = Documento(
        titulo=datos.modelo.nombre,
        subtitulo="Reporte de análisis estructural",
        datos=[
            ("Fecha", op.fecha),
            *([("Elaboró", op.autor)] if op.autor else []),
            ("Motor de análisis", op.motor),
            ("Combinación modal", op.metodo),
            ("Programa", f"estruc-mx {datos.version}"),
        ],
    )
    for nombre in nombres:
        doc.bloques.extend(SECCIONES[nombre](datos))
    return doc.numerar()


def escribir(doc: Documento, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    formato = FORMATOS.get(ruta.suffix.lower())
    if formato == "pdf":
        from .pdf import escribir_pdf as escribir_fmt
    elif formato == "word":
        from .word import escribir_word as escribir_fmt
    else:
        raise ValueError(f"extensión '{ruta.suffix}' no soportada; usar {', '.join(FORMATOS)}")
    escribir_fmt(doc, ruta)
    return ruta


def generar(modelo: Edificio, ruta: str | Path, opciones: Opciones | None = None,
            secciones: list[str] | None = None) -> Path:
    """Analiza el modelo y escribe el reporte en `ruta` (.pdf o .docx)."""
    return escribir(construir(preparar(modelo, opciones), secciones), ruta)


__all__ = ["DatosReporte", "Documento", "Opciones", "SECCIONES", "construir", "escribir", "generar", "preparar"]
