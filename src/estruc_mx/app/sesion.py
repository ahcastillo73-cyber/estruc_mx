"""Estado de una sesión de trabajo, sin dependencias de interfaz gráfica.

La ventana solo muestra lo que la sesión calcula; así la lógica se prueba sin pantalla.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..analisis.espectral import PropiedadesModales, RespuestaEspectral, espectral, propiedades_modales
from ..modelo import Edificio, masas_nodales
from ..motores import Modos, Resultados

MOTORES = ("pynite", "opensees")


def _motor(nombre: str):
    if nombre == "pynite":
        from ..motores import pynite

        return pynite
    if nombre == "opensees":
        from ..motores import opensees

        return opensees
    raise ValueError(f"motor desconocido: {nombre}")


@dataclass
class Tabla:
    titulo: str
    columnas: list[str]
    filas: list[list[object]] = field(default_factory=list)


@dataclass
class Sesion:
    modelo: Edificio | None = None
    ruta: str | None = None
    motor: str = "pynite"
    estatico: Resultados | None = None
    modos: Modos | None = None
    propiedades: PropiedadesModales | None = None
    espectrales: dict[str, RespuestaEspectral] = field(default_factory=dict)

    # --- archivo ----------------------------------------------------------
    def abrir(self, ruta: str) -> None:
        self.modelo = Edificio.cargar(ruta)
        self.ruta = ruta
        self.limpiar_resultados()

    def guardar(self, ruta: str | None = None) -> None:
        self._exigir_modelo()
        self.ruta = ruta or self.ruta
        if not self.ruta:
            raise ValueError("falta la ruta del archivo")
        self.modelo.guardar(self.ruta)

    def exportar_script(self, ruta: str) -> None:
        from ..motores import opensees

        self._exigir_modelo()
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(opensees.generar_script(self.modelo))

    def limpiar_resultados(self) -> None:
        self.estatico = None
        self.modos = None
        self.propiedades = None
        self.espectrales = {}

    # --- análisis -----------------------------------------------------------
    def analizar_estatico(self) -> Resultados:
        self._exigir_modelo()
        self.estatico = _motor(self.motor).analizar(self.modelo)
        return self.estatico

    def analizar_modal(self, n_modos: int = 12) -> Modos:
        self._exigir_modelo()
        self.modos = _motor(self.motor).modal(self.modelo, n_modos)
        self.propiedades = propiedades_modales(self.modelo, self.modos)
        self.espectrales = {}
        return self.modos

    def analizar_espectral(self, direccion: str = "X", metodo: str = "CQC", n_modos: int = 12) -> RespuestaEspectral:
        self._exigir_modelo()
        if self.modos is None:
            self.analizar_modal(n_modos)
        r = espectral(self.modelo, self.modos, direccion, metodo)
        self.espectrales[direccion] = r
        return r

    # --- tablas para mostrar -------------------------------------------------
    def resumen(self) -> Tabla:
        self._exigir_modelo()
        m = self.modelo
        t = Tabla("Modelo", ["Concepto", "Valor"])
        t.filas = [
            ["Nombre", m.nombre],
            ["Nodos", len(m.nodos)],
            ["Barras", len(m.barras)],
            ["Columnas", sum(b.tipo == "columna" for b in m.barras)],
            ["Vigas", sum(b.tipo == "viga" for b in m.barras)],
            ["Materiales", ", ".join(x.nombre for x in m.materiales)],
            ["Secciones", ", ".join(x.nombre for x in m.secciones)],
            ["Patrones de carga", ", ".join(p.nombre for p in m.patrones)],
            ["Combinaciones", len(m.combinaciones)],
        ]
        try:
            t.filas.append(["Masa total (t)", round(sum(masas_nodales(m).values()), 2)])
        except ValueError as e:
            t.filas.append(["Masa", f"error: {e}"])
        t.filas.append(["Espectro", m.espectro.nombre if m.espectro else "sin definir"])
        return t

    def tabla_desplazamientos(self, combinacion: str) -> Tabla:
        if self.estatico is None:
            raise ValueError("primero ejecuta el análisis estático")
        t = Tabla(f"Desplazamientos, {combinacion}", ["Nodo", "X (m)", "Y (m)", "Z (m)", "UX (mm)", "UY (mm)", "UZ (mm)"])
        coords = {n.id: n for n in self.modelo.nodos}
        for nid, d in self.estatico.desplazamientos[combinacion].items():
            n = coords[nid]
            t.filas.append([nid, n.x, n.y, n.z, *(round(v * 1000, 3) for v in d[:3])])
        return t

    def tabla_reacciones(self, combinacion: str) -> Tabla:
        if self.estatico is None:
            raise ValueError("primero ejecuta el análisis estático")
        t = Tabla(f"Reacciones, {combinacion} (kN, kN·m)", ["Nodo", "FX", "FY", "FZ", "MX", "MY", "MZ"])
        suma = [0.0] * 6
        for nid, r in self.estatico.reacciones[combinacion].items():
            t.filas.append([nid, *(round(v, 2) for v in r)])
            suma = [a + b for a, b in zip(suma, r)]
        t.filas.append(["Suma", *(round(v, 2) for v in suma)])
        return t

    def tabla_modal(self) -> Tabla:
        if self.propiedades is None:
            raise ValueError("primero ejecuta el análisis modal")
        p = self.propiedades
        t = Tabla(
            f"Modos (masa total {p.masa_total:.2f} t)",
            ["Modo", "T (s)", "%Mx", "%My", "%Mz", "Acum. X", "Acum. Y"],
        )
        ax, ay = p.fraccion_acumulada("X"), p.fraccion_acumulada("Y")
        for i, T in enumerate(p.periodos):
            t.filas.append([
                i + 1, round(T, 4),
                *(round(p.fraccion_masa[d][i] * 100, 1) for d in "XYZ"),
                round(ax[i] * 100, 1), round(ay[i] * 100, 1),
            ])
        return t

    def tabla_derivas(self, direccion: str) -> Tabla:
        r = self.espectrales.get(direccion)
        if r is None:
            raise ValueError(f"primero ejecuta el análisis espectral en {direccion}")
        t = Tabla(
            f"Espectral {direccion} ({r.metodo}): cortante basal {r.cortante_basal:.1f} kN",
            ["Nivel (m)", "Deriva", "Columna"],
        )
        for d in r.derivas:
            t.filas.append([d.nivel, round(d.deriva, 5), d.barra])
        return t

    def _exigir_modelo(self) -> None:
        if self.modelo is None:
            raise ValueError("no hay modelo abierto")
