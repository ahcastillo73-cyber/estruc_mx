"""Renderizador PDF con ReportLab (Python puro, igual en Linux, macOS y Windows)."""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .bloques import Documento, Figura, Lista, Parrafo, SaltoPagina, Tabla, Titulo

AZUL = colors.HexColor("#1f3b5c")
FONDO = colors.HexColor("#e8eef5")
AVISO = colors.HexColor("#fdecea")


# Helvetica no trae los superíndices fuera de Latin-1
_SUPER = {"⁴": "<super>4</super>", "⁵": "<super>5</super>", "⁶": "<super>6</super>"}


def _x(texto: str) -> str:
    """Escapa texto plano para Paragraph."""
    t = escape(texto)
    for k, v in _SUPER.items():
        t = t.replace(k, v)
    return t


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], textColor=AZUL, fontSize=20, leading=24),
        "subtitulo": ParagraphStyle("subtitulo", parent=base["Normal"], alignment=TA_CENTER, fontSize=12,
                                    textColor=colors.HexColor("#555555"), spaceAfter=14),
        1: ParagraphStyle("h1", parent=base["Heading1"], textColor=AZUL, fontSize=15, spaceBefore=12, spaceAfter=6,
                               keepWithNext=1),
        2: ParagraphStyle("h2", parent=base["Heading2"], textColor=AZUL, fontSize=12, spaceBefore=8, spaceAfter=4,
                               keepWithNext=1),
        "normal": ParagraphStyle("normal", parent=base["BodyText"], fontSize=9.5, leading=13),
        "nota": ParagraphStyle("nota", parent=base["BodyText"], fontSize=8, leading=10,
                               textColor=colors.HexColor("#555555")),
        "aviso": ParagraphStyle("aviso", parent=base["BodyText"], fontSize=9.5, leading=13, backColor=AVISO,
                                borderPadding=4, textColor=colors.HexColor("#8a1c12")),
        "leyenda": ParagraphStyle("leyenda", parent=base["BodyText"], fontSize=8.5, alignment=TA_CENTER,
                                  textColor=colors.HexColor("#333333"), spaceAfter=8),
        "celda": ParagraphStyle("celda", parent=base["BodyText"], fontSize=8, leading=9.5),
        "celda_enc": ParagraphStyle("celda_enc", parent=base["BodyText"], fontSize=8, leading=9.5,
                                    textColor=colors.white, fontName="Helvetica-Bold"),
    }


def _tabla(t: Tabla, est, ancho_util: float):
    n = len(t.encabezados)
    pesos = t.anchos if len(t.anchos) == n else [1.0] * n
    total = sum(pesos)
    anchos = [ancho_util * p / total for p in pesos]
    datos = [[Paragraph(_x(h), est["celda_enc"]) for h in t.encabezados]]
    for fila in t.filas:
        datos.append([Paragraph(_x(str(c)), est["celda"]) for c in fila])
    tabla = Table(datos, colWidths=anchos, repeatRows=1, hAlign="CENTER")
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b5c3d3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i in range(2, len(datos), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), FONDO))
    tabla.setStyle(TableStyle(estilo))
    # Alineación por columna a través del estilo de los párrafos
    for j in range(n):
        if j not in t.texto:
            for fila in datos:
                fila[j].style = ParagraphStyle(f"der{j}", parent=fila[j].style, alignment=2)
    leyenda = [Paragraph(_x(f"{t.numero} {t.titulo}".strip()), est["leyenda"])] if t.titulo else []
    # Las tablas cortas no se parten entre páginas; las largas repiten el encabezado
    if len(t.filas) <= 25:
        return leyenda + [tabla], [Spacer(1, 8)]
    return leyenda, [tabla, Spacer(1, 8)]


def _figura(f: Figura, est, ancho_util: float):
    lector = ImageReader(io.BytesIO(f.png))
    w, h = lector.getSize()
    ancho = ancho_util * f.ancho
    img = Image(io.BytesIO(f.png), width=ancho, height=ancho * h / w)
    partes = [img]
    if f.titulo:
        partes.append(Paragraph(_x(f"{f.numero} {f.titulo}".strip()), est["leyenda"]))
    return partes, []


def escribir_pdf(doc: Documento, ruta: str | Path) -> None:
    est = _estilos()
    margen = 2 * cm
    plantilla = SimpleDocTemplate(
        str(ruta), pagesize=letter, leftMargin=margen, rightMargin=margen, topMargin=margen, bottomMargin=margen,
        title=doc.titulo, subject=doc.subtitulo, author="estruc-mx",
    )
    ancho_util = letter[0] - 2 * margen

    def pie(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(margen, 1.2 * cm, f"{doc.titulo} · {doc.subtitulo}")
        canvas.drawRightString(letter[0] - margen, 1.2 * cm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    historia = [Paragraph(_x(doc.titulo), est["titulo"])]
    if doc.subtitulo:
        historia.append(Paragraph(_x(doc.subtitulo), est["subtitulo"]))
    if doc.datos:
        portada = Table(
            [[Paragraph(f"<b>{_x(k)}</b>", est["celda"]), Paragraph(_x(v), est["celda"])] for k, v in doc.datos],
            colWidths=[ancho_util * 0.3, ancho_util * 0.5], hAlign="CENTER",
        )
        portada.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#b5c3d3"))]))
        historia += [portada, Spacer(1, 12)]

    # Los títulos se juntan con el primer elemento que les sigue para no quedar solos al pie
    titulos: list = []
    for b in doc.bloques:
        if isinstance(b, Titulo):
            titulos.append(Paragraph(_x(b.completo), est[min(b.nivel, 2)]))
            continue
        # juntos: lo que no se debe separar (ni del título previo); resto: lo que puede fluir
        if isinstance(b, Parrafo):
            juntos, resto = [Paragraph(_x(b.texto), est.get(b.estilo, est["normal"]))], [Spacer(1, 4)]
        elif isinstance(b, Lista):
            juntos, resto = [ListFlowable(
                [ListItem(Paragraph(_x(e), est["normal"])) for e in b.elementos], bulletType="bullet",
            )], []
        elif isinstance(b, Tabla):
            juntos, resto = _tabla(b, est, ancho_util)
        elif isinstance(b, Figura):
            juntos, resto = _figura(b, est, ancho_util)
        else:  # SaltoPagina
            historia += titulos + [PageBreak()]
            titulos = []
            continue
        historia.append(KeepTogether(titulos + juntos))
        historia += resto
        titulos = []
    historia += titulos
    plantilla.build(historia, onFirstPage=pie, onLaterPages=pie)
