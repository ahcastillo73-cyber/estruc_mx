"""Dibuja el icono de la aplicación (un pórtico de dos niveles) en PNG, ICO e ICNS.

    python empaquetado/iconos.py

Usa Pillow, que ya viene con matplotlib. Los archivos se generan en la CI antes de
empaquetar y no se guardan en el repositorio.
"""

from pathlib import Path

from PIL import Image, ImageDraw

AQUI = Path(__file__).parent


def dibujar(n: int = 1024) -> Image.Image:
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = n // 16
    d.rounded_rectangle([m, m, n - m, n - m], radius=n // 6, fill=(28, 61, 102, 255))
    g = n // 22  # grosor de barra
    x = [int(n * f) for f in (0.24, 0.50, 0.76)]
    y = [int(n * f) for f in (0.76, 0.50, 0.26)]  # base, nivel 1, nivel 2
    acero = (236, 240, 245, 255)
    for xi in x:
        d.rectangle([xi - g // 2, y[2], xi + g // 2, y[0]], fill=acero)
    for yi in y[1:]:
        d.rectangle([x[0], yi - g // 2, x[2], yi + g // 2], fill=acero)
    # apoyos empotrados
    naranja = (240, 140, 40, 255)
    for xi in x:
        d.rectangle([xi - 2 * g, y[0], xi + 2 * g, y[0] + g], fill=naranja)
    return im


def main() -> None:
    im = dibujar()
    im.save(AQUI / "linux" / "estruc-mx.png")
    im.save(AQUI / "windows" / "estruc-mx.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    try:
        im.save(AQUI / "macos" / "estruc-mx.icns")
    except Exception as e:  # noqa: BLE001 - el icono es opcional
        print("no se generó .icns:", e)
    print("iconos listos en", AQUI)


if __name__ == "__main__":
    main()
