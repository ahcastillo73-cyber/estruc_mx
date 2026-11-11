"""Espectros de diseño sísmico. Las ordenadas están en fracciones de g.

- `EspectroTabular`: pares (T, Sa) interpolados linealmente. Es la forma más segura de usar
  el espectro de sitio que entrega SASID (NTC Sismo, CDMX) o el programa PRODISIS (CFE).
- `EspectroNTC`: forma paramétrica de las NTC Diseño por Sismo (2017 en adelante), con los
  parámetros a0, c, Ta, Tb y k que entrega SASID. Verificar la fórmula contra la edición
  vigente antes de usarla en un proyecto.

En ambos casos `reduccion` divide las ordenadas (por ejemplo Q'·R de las NTC); por defecto 1,
es decir, espectro elástico.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

import numpy as np
from pydantic import BaseModel, Field, model_validator


class EspectroTabular(BaseModel):
    tipo: Literal["tabular"] = "tabular"
    nombre: str = "Espectro"
    T: list[float] = Field(description="Periodos, s, crecientes")
    Sa: list[float] = Field(description="Aceleración espectral, fracción de g")
    reduccion: float = Field(1.0, gt=0)

    @model_validator(mode="after")
    def _validar(self) -> "EspectroTabular":
        if len(self.T) != len(self.Sa) or len(self.T) < 2:
            raise ValueError("T y Sa deben tener la misma longitud (al menos 2 puntos)")
        if any(b <= a for a, b in zip(self.T, self.T[1:])):
            raise ValueError("los periodos T deben ser estrictamente crecientes")
        return self

    def sa(self, T: float) -> float:
        """Sa(T) en g; fuera del rango se mantiene el valor extremo."""
        return float(np.interp(T, self.T, self.Sa)) / self.reduccion


class EspectroNTC(BaseModel):
    """a = a0 + (βc − a0)·T/Ta          si T < Ta
       a = βc                           si Ta ≤ T < Tb
       a = βc·p·(Tb/T)²,  p = k + (1 − k)(Tb/T)²   si T ≥ Tb
    """

    tipo: Literal["ntc"] = "ntc"
    nombre: str = "Espectro NTC"
    a0: float = Field(gt=0, description="Aceleración máxima del terreno, g")
    c: float = Field(gt=0, description="Coeficiente sísmico (meseta), g")
    Ta: float = Field(gt=0, description="s")
    Tb: float = Field(gt=0, description="s")
    k: float = Field(ge=0, description="Parámetro de la rama descendente")
    beta: float = Field(1.0, gt=0, description="Factor de amortiguamiento (1 para 5 %)")
    reduccion: float = Field(1.0, gt=0)

    @model_validator(mode="after")
    def _validar(self) -> "EspectroNTC":
        if self.Tb < self.Ta:
            raise ValueError("Tb debe ser mayor o igual que Ta")
        return self

    def sa(self, T: float) -> float:
        bc = self.beta * self.c
        if T < self.Ta:
            a = self.a0 + (bc - self.a0) * T / self.Ta
        elif T < self.Tb:
            a = bc
        else:
            r = (self.Tb / T) ** 2
            a = bc * (self.k + (1.0 - self.k) * r) * r
        return a / self.reduccion


Espectro = Annotated[Union[EspectroTabular, EspectroNTC], Field(discriminator="tipo")]
