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
    return preparar(construir_marco(), Opciones(n_modos=6, sistema="marco_ductil_concreto"))


def test_preparar_corre_todos_los_analisis(datos):
    assert datos.estatico is not None and datos.modos is not None
    assert set(datos.espectral) == {"X", "Y"}
    assert datos.avisos == []


def test_documento_tiene_todas_las_secciones_numeradas(datos):
    doc = construir(datos)
    titulos = [b for b in doc.bloques if isinstance(b, Titulo) and b.nivel == 1]
    assert len(titulos) == len(SECCIONES)
    assert [t.numero for t in titulos] == [f"{i}." for i in range(1, len(SECCIONES) + 1)]
    figuras = [b for b in doc.bloques if isinstance(b, Figura)]
    assert figuras and all(f.png.startswith(b"\x89PNG") for f in figuras)
    assert all(f.numero.startswith("Figura") for f in figuras)


def test_derivas_comparan_contra_limite(datos):
    doc = construir(datos, ["derivas"])
    tabla = next(b for b in doc.bloques if isinstance(b, Tabla))
    assert tabla.encabezados[-1] == "Cumple"
    assert len(tabla.filas) == 3  # tres niveles
    # La distorsión de la tabla es la del análisis espectral por el factor (1 con espectro elástico)
    x = datos.espectral["X"].derivas[0].deriva
    assert float(tabla.filas[0][1]) == pytest.approx(x, abs=1e-5)


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
    assert "marco_ductil_concreto" in capsys.readouterr().out
