"""Estado de una sesión de trabajo, sin dependencias de interfaz gráfica.

La ventana solo muestra lo que la sesión calcula; así la lógica se prueba sin pantalla.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..analisis.espectral import PropiedadesModales, RespuestaEspectral, espectral, propiedades_modales
from ..modelo import Edificio, Editor, Rejilla, masas_nodales
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
    # Por fila: "cumple", "no cumple" o None, para colorear la tabla
    estados: list[str | None] = field(default_factory=list)


@dataclass
class Sesion:
    """El modelo vive en `editor` (con su historia); cualquier cambio descarta los resultados."""

    editor: Editor = field(default_factory=Editor)
    ruta: str | None = None
    motor: str = "pynite"
    estatico: Resultados | None = None
    modos: Modos | None = None
    propiedades: PropiedadesModales | None = None
    espectrales: dict[str, RespuestaEspectral] = field(default_factory=dict)
    revision: object | None = None  # RevisionSismica
    mamposteria: object | None = None  # RevisionMamposteria

    def __post_init__(self) -> None:
        self.editor.observadores.append(self.limpiar_resultados)

    @property
    def modelo(self) -> Edificio | None:
        return self.editor.modelo

    @property
    def modificado(self) -> bool:
        return self.editor.modificado

    # --- archivo ----------------------------------------------------------
    def nuevo(self, nombre: str, rejilla: Rejilla | None = None) -> None:
        self.editor.nuevo(nombre, rejilla)
        self.ruta = None

    def abrir(self, ruta: str) -> None:
        self.editor.cargar(Edificio.cargar(ruta))
        self.ruta = ruta

    def guardar(self, ruta: str | None = None) -> None:
        self._exigir_modelo()
        self.ruta = ruta or self.ruta
        if not self.ruta:
            raise ValueError("falta la ruta del archivo")
        self.modelo.guardar(self.ruta)
        self.editor.modificado = False

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
        self.revision = None
        self.mamposteria = None

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
        self.revision = None
        return self.modos

    def analizar_espectral(self, direccion: str = "X", metodo: str = "CQC", n_modos: int = 12) -> RespuestaEspectral:
        self._exigir_modelo()
        if self.modos is None:
            self.analizar_modal(n_modos)
        r = espectral(self.modelo, self.modos, direccion, metodo)
        self.espectrales[direccion] = r
        self.revision = None
        return r

    def revisar_mamposteria(self, n_modos: int = 12, criterios_sismo=None, criterios=None):
        """Revisión de muros de mampostería (NTC Mampostería 2023). Corre lo que falte: estático,
        y si hay masa y espectro, modal, espectral en X y Y y la revisión sísmica."""
        from ..analisis.revision_sismica import revisar
        from ..diseno.mamposteria import revisar_mamposteria

        self._exigir_modelo()
        m = self.modelo
        motor = _motor(self.motor)
        if self.estatico is None and m.patrones:
            self.analizar_estatico()
        if m.espectro is not None:
            try:
                for d in ("X", "Y"):
                    if d not in self.espectrales:
                        self.analizar_espectral(d, "CQC", n_modos)
                if self.revision is None:
                    self.revision = revisar(m, self.modos, self.espectrales, motor, criterios_sismo)
            except ValueError:
                self.revision = None  # sin masa: solo gravedad
        self.mamposteria = revisar_mamposteria(m, self.estatico, self.revision, self.espectrales or None, motor, criterios)
        return self.mamposteria

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
            ["Muros", sum(a.tipo == "muro" for a in m.areas)],
            ["Losas", sum(a.tipo == "losa" for a in m.areas)],
            ["Materiales", ", ".join(x.nombre for x in m.materiales)],
            ["Secciones", ", ".join(x.nombre for x in m.secciones)],
            *([["Secciones de muro y losa", ", ".join(x.nombre for x in m.secciones_area)]] if m.areas else []),
            *([["Tamaño de malla (m)", m.tamano_malla]] if m.areas else []),
            ["Patrones de carga", ", ".join(p.nombre for p in m.patrones)],
            ["Combinaciones", len(m.combinaciones)],
        ]
        try:
            t.filas.append(["Masa total (t)", round(sum(masas_nodales(m).values()), 2)])
        except ValueError as e:
            t.filas.append(["Masa", f"error: {e}"])
        t.filas.append(["Espectro", m.espectro.nombre if m.espectro else "sin definir"])
        if m.diafragmas:
            t.filas.append(["Diafragmas rígidos", ", ".join(d.nombre for d in m.diafragmas)])
        return t

    def tabla_diafragmas(self) -> Tabla:
        """Centro de masa de cada diafragma (el desplazamiento del centro sale en Desplazamientos)."""
        from ..modelo.malla import discretizar

        self._exigir_modelo()
        malla = discretizar(self.modelo)
        t = Tabla("Diafragmas rígidos: centro de masa", ["Diafragma", "Z (m)", "Masa (t)", "X CM (m)", "Y CM (m)", "Nodos"])
        for d in malla.diafragmas:
            t.filas.append([
                d.nombre, d.z, round(d.masa, 3), round(float(d.centro[0]), 3), round(float(d.centro[1]), 3), len(d.esclavos),
            ])
        if not malla.diafragmas:
            t.titulo += " (ninguno aplicado)"
        for aviso in (a for a in malla.avisos if a.startswith("Diafragma")):
            t.titulo += f". {aviso}"
        return t

    def tabla_desplazamientos(self, combinacion: str) -> Tabla:
        if self.estatico is None:
            raise ValueError("primero ejecuta el análisis estático")
        t = Tabla(f"Desplazamientos, {combinacion}", ["Nodo", "X (m)", "Y (m)", "Z (m)", "UX (mm)", "UY (mm)", "UZ (mm)"])
        tabla = self.estatico.desplazamientos[combinacion]
        # Solo los nodos del modelo; los de la malla de muros y losas se ven en la deformada
        for n in self.modelo.nodos:
            t.filas.append([n.id, n.x, n.y, n.z, *(round(v * 1000, 3) for v in tabla[n.id][:3])])
        # Centros de masa de los diafragmas (nodos maestros)
        from ..modelo.malla import discretizar

        for d in discretizar(self.modelo).diafragmas:
            if d.maestro in tabla:
                x, y, z = (round(float(v), 3) for v in d.centro)
                t.filas.append([d.maestro, x, y, z, *(round(v * 1000, 3) for v in tabla[d.maestro][:3])])
        return t

    def tabla_muros(self, combinacion: str) -> Tabla:
        from ..analisis.areas import todas_fuerzas_muros
        from ..modelo.malla import discretizar

        if self.estatico is None:
            raise ValueError("primero ejecuta el análisis estático")
        m = self.modelo
        f = todas_fuerzas_muros(m, discretizar(m), self.estatico.fuerzas_elementos.get(combinacion, {}))
        t = Tabla(
            f"Fuerzas en la base de los muros, {combinacion} (kN, kN·m; P > 0 tensión)",
            ["Muro", "Sección", "Base (m)", "P", "V", "M", "V fuera", "M fuera"],
        )
        for a in m.areas:
            if a.id in f:
                x = f[a.id]
                z = min(m.nodo(n).z for n in a.nodos)
                t.filas.append([a.id, a.seccion, z, *(round(x[c], 2) for c in ("P", "V", "M", "Vfp", "Mfp"))])
        return t

    def tabla_losas(self, combinacion: str) -> Tabla:
        from ..analisis.areas import esfuerzos_areas, extremos_esfuerzos
        from ..modelo.malla import discretizar

        if self.estatico is None:
            raise ValueError("primero ejecuta el análisis estático")
        m = self.modelo
        esf = esfuerzos_areas(m, discretizar(m), self.estatico.desplazamientos[combinacion])
        t = Tabla(
            f"Momentos en losas, {combinacion} (kN·m/m; + tensión abajo)",
            ["Losa", "M11 mín", "M11 máx", "M22 mín", "M22 máx", "|M12| máx"],
        )
        for a in m.areas:
            if a.tipo == "losa":
                e = extremos_esfuerzos(esf[a.id])
                t.filas.append([
                    a.id, *(round(v, 2) for v in (*e["M11"], *e["M22"])),
                    round(max(abs(v) for v in e["M12"]), 2),
                ])
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
            ["Nivel (m)", "Deriva", "Columna o muro"],
        )
        for d in r.derivas:
            t.filas.append([d.nivel, round(d.deriva, 5), d.barra])
        return t

    def tabla_muros_espectral(self, direccion: str) -> Tabla:
        r = self.espectrales.get(direccion)
        if r is None:
            raise ValueError(f"primero ejecuta el análisis espectral en {direccion}")
        t = Tabla(
            f"Fuerzas en muros, espectral {direccion} ({r.metodo}), valores máximos (kN, kN·m)",
            ["Muro", "P", "V", "M", "V fuera", "M fuera"],
        )
        for a in self.modelo.areas:
            if a.id in r.fuerzas_muros:
                x = r.fuerzas_muros[a.id]
                t.filas.append([a.id, *(round(x[c], 2) for c in ("P", "V", "M", "Vfp", "Mfp"))])
        return t

    def tabla_mamposteria(self) -> Tabla:
        r = self.mamposteria
        if r is None:
            raise ValueError("primero ejecuta la revisión de mampostería")
        t = Tabla(
            "Muros de mampostería, NTC Mampostería 2023 (kN, kN·m). " + (
                "Cumplen todos." if r.cumple else "Hay muros o entrepisos que no cumplen."),
            ["Muro", "Base (m)", "Dir.", "L (m)", "t (cm)", "Pu", "PR", "Vu", "VR", "Mu", "MR", "D/C", "Requisitos",
             "Estado"],
        )
        for w in r.muros:
            fallas = [c.concepto for c in w.comprobaciones if not c.resistencia and not c.cumple]
            t.filas.append([
                w.muro, round(w.z, 2), w.direccion, round(w.L, 2), round(w.t * 100, 1), round(w.Pu, 1), round(w.PR, 1),
                "-" if w.Vu is None else round(w.Vu, 1), round(w.VR, 1) if w.Vu is not None else "-",
                "-" if w.Mu is None else round(w.Mu, 1), "-" if w.MR is None else round(w.MR, 1),
                round(w.relacion, 2), "cumplen" if not fallas else "; ".join(fallas),
                "cumple" if w.cumple else "no cumple",
            ])
            t.estados.append("cumple" if w.cumple else "no cumple")
        return t

    def tabla_mamposteria_detalle(self) -> Tabla:
        r = self.mamposteria
        if r is None:
            raise ValueError("primero ejecuta la revisión de mampostería")
        t = Tabla("Revisiones por muro (valor contra límite o demanda contra resistencia); primero las que no cumplen",
                  ["Muro", "Revisión", "Artículo", "Valor / demanda", "Límite / resistencia", "Unidad", "Estado", "Detalle"])
        pares = [(w, c) for w in r.muros for c in w.comprobaciones]
        for w, c in sorted(pares, key=lambda x: x[1].cumple):
            t.filas.append([
                w.muro, c.concepto, c.articulo, "-" if c.demanda is None else round(c.demanda, 3),
                "-" if c.capacidad is None else round(c.capacidad, 3), c.unidad,
                "cumple" if c.cumple else "no cumple", c.detalle,
            ])
            t.estados.append("cumple" if c.cumple else "no cumple")
        return t

    def tabla_mamposteria_entrepisos(self) -> Tabla:
        r = self.mamposteria
        if r is None:
            raise ValueError("primero ejecuta la revisión de mampostería")
        t = Tabla("Cortante resistente de entrepiso, VRi ≥ 0.8·Vui (NTC Mampostería 4.1.10)",
                  ["Dirección", "Entrepiso (m)", "Muros", "ΣAT (m²)", "σ (kPa)", "VR (kN)", "0.8·Vu (kN)", "Estado"])
        for e in r.entrepisos:
            t.filas.append([e.direccion, f"{e.z_base:g}–{e.z_tope:g}", len(e.muros), round(e.AT, 3), round(e.sigma, 1),
                            round(e.VR, 1), round(0.8 * e.Vu, 1), "cumple" if e.cumple else "no cumple"])
            t.estados.append("cumple" if e.cumple else "no cumple")
        return t

    def _exigir_modelo(self) -> None:
        if self.modelo is None:
            raise ValueError("no hay modelo abierto")
