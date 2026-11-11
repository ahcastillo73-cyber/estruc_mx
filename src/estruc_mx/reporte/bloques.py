"""Bloques del reporte: contenido sin formato, independiente del formato de salida.

Cada sección del reporte es una función que devuelve una lista de bloques. Los
renderizadores (`pdf.py`, `word.py`) solo saben dibujar bloques, así que una sección
nueva aparece en todos los formatos sin tocarlos, y un formato nuevo (HTML, LaTeX)
solo tiene que implementar estos seis tipos.

El texto es plano: los renderizadores escapan lo que haga falta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Titulo:
    texto: str
    nivel: int = 1  # 1 = sección, 2 = subsección
    numero: str = ""  # lo asigna `Documento.numerar`

    @property
    def completo(self) -> str:
        return f"{self.numero} {self.texto}" if self.numero else self.texto


@dataclass
class Parrafo:
    texto: str
    estilo: str = "normal"  # "normal", "nota" (letra menor) o "aviso" (resaltado)


@dataclass
class Lista:
    elementos: list[str]


@dataclass
class Tabla:
    encabezados: list[str]
    filas: list[list[str]]
    titulo: str = ""
    # Ancho relativo de cada columna; vacío = repartir igual
    anchos: list[float] = field(default_factory=list)
    # Índices de columnas alineadas a la izquierda (el resto, números, a la derecha)
    texto: set[int] = field(default_factory=lambda: {0})
    numero: str = ""  # lo asigna `Documento.numerar`


@dataclass
class Figura:
    png: bytes
    titulo: str = ""
    ancho: float = 0.9  # fracción del ancho útil de la página
    numero: str = ""  # lo asigna `Documento.numerar`


@dataclass
class SaltoPagina:
    pass


Bloque = Union[Titulo, Parrafo, Lista, Tabla, Figura, SaltoPagina]


@dataclass
class Documento:
    titulo: str
    subtitulo: str = ""
    # Pares (etiqueta, valor) de la portada: proyecto, fecha, motor, versión...
    datos: list[tuple[str, str]] = field(default_factory=list)
    bloques: list[Bloque] = field(default_factory=list)

    def numerar(self) -> "Documento":
        """Numera secciones (1, 1.1), tablas y figuras en el orden en que aparecen."""
        sec = sub = tab = fig = 0
        for b in self.bloques:
            if isinstance(b, Titulo):
                if b.nivel == 1:
                    sec, sub = sec + 1, 0
                    b.numero = f"{sec}."
                else:
                    sub += 1
                    b.numero = f"{sec}.{sub}"
            elif isinstance(b, Tabla) and b.titulo:
                tab += 1
                b.numero = f"Tabla {tab}."
            elif isinstance(b, Figura) and b.titulo:
                fig += 1
                b.numero = f"Figura {fig}."
        return self
