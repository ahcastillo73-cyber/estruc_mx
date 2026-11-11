"""Renderizador Word (.docx) con python-docx. Mismos bloques que el PDF."""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from .bloques import Documento, Figura, Lista, Parrafo, SaltoPagina, Tabla, Titulo

ANCHO_UTIL_CM = 17.0


def _leyenda(d, texto: str) -> None:
    p = d.add_paragraph()
    r = p.add_run(texto)
    r.font.size = Pt(8.5)
    r.italic = True
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def escribir_word(doc: Documento, ruta: str | Path) -> None:
    from docx.shared import Cm

    d = Document()
    d.core_properties.title = doc.titulo
    d.core_properties.subject = doc.subtitulo
    d.add_heading(doc.titulo, level=0)
    if doc.subtitulo:
        d.add_paragraph(doc.subtitulo)
    if doc.datos:
        t = d.add_table(rows=0, cols=2)
        t.style = "Light List"
        for k, v in doc.datos:
            fila = t.add_row().cells
            fila[0].text, fila[1].text = k, v
            fila[0].paragraphs[0].runs[0].bold = True

    for b in doc.bloques:
        if isinstance(b, Titulo):
            d.add_heading(b.completo, level=min(b.nivel, 2))
        elif isinstance(b, Parrafo):
            p = d.add_paragraph()
            r = p.add_run(b.texto)
            if b.estilo == "nota":
                r.font.size = Pt(8)
            elif b.estilo == "aviso":
                r.bold = True
                r.font.color.rgb = RGBColor(0x8A, 0x1C, 0x12)
        elif isinstance(b, Lista):
            for e in b.elementos:
                d.add_paragraph(e, style="List Bullet")
        elif isinstance(b, Tabla):
            if b.titulo:
                _leyenda(d, f"{b.numero} {b.titulo}".strip())
            t = d.add_table(rows=1, cols=len(b.encabezados))
            t.style = "Light Grid Accent 1"
            for c, h in zip(t.rows[0].cells, b.encabezados):
                c.text = h
            for fila in b.filas:
                celdas = t.add_row().cells
                for j, (c, v) in enumerate(zip(celdas, fila)):
                    c.text = str(v)
                    if j not in b.texto:
                        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for fila in t.rows:
                for c in fila.cells:
                    for r in c.paragraphs[0].runs:
                        r.font.size = Pt(8)
            d.add_paragraph()
        elif isinstance(b, Figura):
            d.add_picture(io.BytesIO(b.png), width=Cm(ANCHO_UTIL_CM * b.ancho))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            if b.titulo:
                _leyenda(d, f"{b.numero} {b.titulo}".strip())
        elif isinstance(b, SaltoPagina):
            d.add_page_break()
    d.save(str(ruta))
