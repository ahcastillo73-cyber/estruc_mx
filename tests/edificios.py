"""Modelos de prueba con muros y losas (fuera de conftest para poder importarlos)."""

from estruc_mx.modelo import CargaNodal, Combinacion, Editor, EspectroNTC, PatronCarga, Rejilla


def edificio_muros(tamano_malla: float = 1.0):
    """Edificio de concreto de 2 crujías × 1, 2 niveles: marco, losas en todos los tableros,
    un muro de concreto en el eje 1 (A–B) y uno de tabique en el eje B (1–2), en ambos niveles."""
    ed = Editor()
    ed.nuevo("Edificio con muros", Rejilla.regular([6.0, 4.0], [5.0], [3.0, 3.0]))
    ed.marco_desde_rejilla("C40x40", "V25x50")
    ed.losas_desde_rejilla("Losa 10")
    for z0, z1 in ((0.0, 3.0), (3.0, 6.0)):
        ed.agregar_muro((0.0, 0.0), (6.0, 0.0), z0, z1, "Muro concreto 15")
        ed.agregar_muro((6.0, 0.0), (6.0, 5.0), z0, z1, "Muro tabique 14")
    m = ed.modelo
    ed.asignar_carga_area([a.id for a in m.areas if a.tipo == "losa"], "CM", "Z", -5.0)
    ed.asignar_carga_area([a.id for a in m.areas if a.tipo == "losa"], "CV", "Z", -2.0)
    ed.definir_malla(tamano_malla)
    m = ed.modelo.model_copy(deep=True)
    m.patrones.append(PatronCarga(nombre="SX", tipo="sismo"))
    m.patrones.append(PatronCarga(nombre="SY", tipo="sismo"))
    for nivel, F in (("N1", 50.0), ("N2", 100.0)):
        m.cargas_nodales.append(CargaNodal(patron="SX", nodo=f"C2-{nivel}", fuerzas=(F, 0, 0, 0, 0, 0)))
        m.cargas_nodales.append(CargaNodal(patron="SY", nodo=f"A2-{nivel}", fuerzas=(0, F, 0, 0, 0, 0)))
    m.combinaciones.append(Combinacion(nombre="CM+SX", factores={"CM": 1.0, "SX": 1.0}))
    m.combinaciones.append(Combinacion(nombre="CM+SY", factores={"CM": 1.0, "SY": 1.0}))
    m.espectro = EspectroNTC(nombre="Ilustrativo", a0=0.15, c=0.45, Ta=0.4, Tb=1.2, k=1.0)
    m.fuente_masa = {"CM": 1.0, "CV": 0.4}
    return type(m).model_validate(m.model_dump())
