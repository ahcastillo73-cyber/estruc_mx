"""Resultados comunes a todos los motores, siempre en ejes globales del modelo (Z arriba).

Los desplazamientos incluyen los nodos generados al dividir muros y losas (modelo/malla.py)."""

from __future__ import annotations

from dataclasses import dataclass, field

# combinación -> nodo -> [UX, UY, UZ, RX, RY, RZ]
Tabla = dict[str, dict[str, list[float]]]


@dataclass
class Resultados:
    motor: str
    desplazamientos: Tabla = field(default_factory=dict)
    # combinación -> nodo -> [FX, FY, FZ, MX, MY, MZ]
    reacciones: Tabla = field(default_factory=dict)
    # combinación -> elemento de cáscara -> 24 fuerzas que sus 4 nodos ejercen sobre él,
    # [FX, FY, FZ, MX, MY, MZ] por nodo en ejes globales (ver analisis/areas.py)
    fuerzas_elementos: Tabla = field(default_factory=dict)

    @property
    def combinaciones(self) -> list[str]:
        return list(self.desplazamientos)

    def desplazamiento_maximo(self, combinacion: str, gdl: int) -> tuple[str, float]:
        """Nodo y valor con el mayor desplazamiento absoluto en el grado de libertad dado (0=UX ... 5=RZ)."""
        tabla = self.desplazamientos[combinacion]
        nodo = max(tabla, key=lambda n: abs(tabla[n][gdl]))
        return nodo, tabla[nodo][gdl]


@dataclass
class Modos:
    """Periodos y formas modales; las formas tienen normalización arbitraria."""

    motor: str
    periodos: list[float] = field(default_factory=list)
    # por modo: nodo -> [UX, UY, UZ, RX, RY, RZ]
    formas: list[dict[str, list[float]]] = field(default_factory=list)
    # por modo: elemento de cáscara -> 24 fuerzas nodales de la forma modal (como en Resultados)
    fuerzas_elementos: list[dict[str, list[float]]] = field(default_factory=list)
