from pathlib import Path

from estruc_mx.cli import main

EJEMPLO = str(Path(__file__).resolve().parent.parent / "ejemplos" / "marco_3niveles.json")


def test_analizar_imprime_resumen(capsys):
    assert main(["analizar", EJEMPLO]) == 0
    salida = capsys.readouterr().out
    assert "1.1CM+SX" in salida and "UX" in salida


def test_exporta_script(tmp_path):
    destino = tmp_path / "m.py"
    assert main(["script", EJEMPLO, "-o", str(destino)]) == 0
    assert "ops.element('elasticBeamColumn'" in destino.read_text(encoding="utf-8")


def test_modal_y_espectral(capsys):
    assert main(["modal", EJEMPLO, "--modos", "6"]) == 0
    assert "acum X" in capsys.readouterr().out
    assert main(["espectral", EJEMPLO, "--direccion", "Y", "--modos", "6"]) == 0
    assert "Cortante basal" in capsys.readouterr().out
