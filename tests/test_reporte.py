import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("reportlab")

from estruc_mx.cli import main  # noqa: E402
from estruc_mx.reporte import SECCIONES, Opciones, construir, escribir, preparar  # noqa: E402
from estruc_mx.reporte.bloques import Figura, Tabla, Titulo  # noqa: E402

from conftest import construir_marco  # noqa: E402
from test_cli import EJEMPLO  # noqa: E402


@pytest.fixture(scope="module")
def datos():
    return preparar(construir_marco(), Opciones(n_modos=6, sistema="marco_concreto_alta"))


def test_preparar_corre_todos_los_analisis(datos):
    assert datos.estatico is not None and datos.modos is not None
    assert set(datos.espectral) == {"X", "Y"}
    assert datos.avisos == []


def test_documento_tiene_todas_las_secciones_numeradas(datos):
    doc = construir(datos)
    titulos = [b for b in doc.bloques if isinstance(b, Titulo) and b.nivel == 1]
    # «muros» no aparece en un modelo sin muros ni losas
    assert len(titulos) == len(SECCIONES) - 1
    assert [t.numero for t in titulos] == [f"{i}." for i in range(1, len(SECCIONES))]
    figuras = [b for b in doc.bloques if isinstance(b, Figura)]
    assert figuras and all(f.png.startswith(b"\x89PNG") for f in figuras)
    assert all(f.numero.startswith("Figura") for f in figuras)


def test_derivas_comparan_contra_limite(datos):
    doc = construir(datos, ["derivas"])
    tabla = next(b for b in doc.bloques if isinstance(b, Tabla))
    assert tabla.encabezados[-1] == "Cumple"
    assert len(tabla.filas) == 3  # tres niveles
    # La distorsión de la tabla es la de la revisión (con torsión y 100/30) por el factor (1 con
    # espectro elástico), mayor que la del análisis espectral solo
    x = datos.revision.derivas["X"][0].deriva
    assert float(tabla.filas[0][1]) == pytest.approx(x, abs=1e-5)
    assert x > datos.espectral["X"].derivas[0].deriva


def test_revision_sismica_en_el_reporte(datos):
    doc = construir(datos, ["cortante", "torsion", "derivas"])
    titulos = [t.titulo for t in doc.bloques if isinstance(t, Tabla)]
    assert "Revisión del cortante basal mínimo" in titulos
    assert any(t.startswith("Torsión accidental") for t in titulos)
    assert "Fórmulas de referencia" in titulos
    # Sin zona ni espectro de servicio, la Limitación de Daño queda pendiente y se avisa
    assert "Distorsiones para Limitación de Daño" not in titulos
    d2 = preparar(construir_marco(), Opciones(n_modos=6, sistema="marco_concreto_alta", zona="B", periodo_sitio=0.75))
    titulos = [t.titulo for t in construir(d2, ["derivas"]).bloques if isinstance(t, Tabla)]
    assert "Distorsiones para Limitación de Daño" in titulos
    # Grupo A: Ocupación Inmediata contra γOI en lugar de Limitación de Daño
    d3 = preparar(construir_marco(), Opciones(n_modos=6, sistema="marco_concreto_alta", grupo="A"))
    tablas = [t for t in construir(d3, ["derivas"]).bloques if isinstance(t, Tabla)]
    oi = next(t for t in tablas if t.titulo == "Distorsiones para Ocupación Inmediata")
    assert oi.encabezados[-1] == "Cumple"
    assert "Distorsiones para Limitación de Daño" not in [t.titulo for t in tablas]


def test_seccion_desconocida(datos):
    with pytest.raises(ValueError, match="desconocidas"):
        construir(datos, ["nada"])


def test_sin_espectro_avisa(datos):

    m = construir_marco()
    m.espectro = None
    d = preparar(m, Opciones(n_modos=4))
    doc = construir(d, ["cortante", "derivas"])
    assert any("espectro" in a for a in d.avisos)
    assert not any(isinstance(b, Tabla) for b in doc.bloques)


def test_escribe_pdf(datos, tmp_path):
    ruta = escribir(construir(datos), tmp_path / "r.pdf")
    assert ruta.read_bytes().startswith(b"%PDF")


def test_escribe_word(datos, tmp_path):
    pytest.importorskip("docx")
    ruta = escribir(construir(datos, ["modelo", "derivas"]), tmp_path / "r.docx")
    from docx import Document

    texto = "\n".join(p.text for p in Document(str(ruta)).paragraphs)
    assert "1. Descripción del modelo" in texto and "Distorsiones de entrepiso" in texto


def test_cli_reporte(tmp_path, capsys):
    destino = tmp_path / "reporte.pdf"
    assert main(["reporte", EJEMPLO, "-o", str(destino), "--modos", "6", "--deriva-limite", "0.015"]) == 0
    assert destino.read_bytes().startswith(b"%PDF")
    assert main(["reporte", "--sistemas"]) == 0
    assert "marco_concreto_alta" in capsys.readouterr().out


def test_reporte_con_muros_y_losas(tmp_path):
    from edificios import edificio_muros

    d = preparar(edificio_muros(), Opciones(n_modos=6, sistema="mamposteria_confinada"))
    doc = construir(d)
    tablas = {b.titulo: b for b in doc.bloques if isinstance(b, Tabla)}
    assert "Secciones de muro y losa" in tablas
    muros = tablas["Fuerzas en la base de los muros, CM+SX"]
    assert [f[0] for f in muros.filas] == ["M1", "M2", "M3", "M4"]
    assert "Fuerzas en muros, sismo en X (CQC, máximos sin signo)" in tablas
    assert len(tablas["Momentos en losas (kN·m/m), CM+CV"].filas) == 4
    for ext in (".pdf", ".docx"):
        assert escribir(doc, tmp_path / f"r{ext}").stat().st_size > 10_000


def test_reporte_con_diafragmas(tmp_path):
    from test_editor_niveles import con_diafragmas

    m = con_diafragmas(construir_marco())
    doc = construir(preparar(m, Opciones(n_modos=6)), ["modelo"])
    tablas = [b for b in doc.bloques if isinstance(b, Tabla) and b.titulo.startswith("Diafragmas")]
    assert len(tablas) == 1 and len(tablas[0].filas) == 3
    escribir(doc, tmp_path / "r.pdf")
