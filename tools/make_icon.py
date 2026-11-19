"""Генератор иконки chess.skay (PIL)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "resources" / "icon.png"

SIZE = 512


def main() -> None:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # фон с градиентом
    for y in range(SIZE):
        t = y / SIZE
        r = int(18 + 20 * t)
        g = int(28 + 28 * t)
        b = int(42 + 40 * t)
        draw.line((0, y, SIZE, y), fill=(r, g, b, 255))

    # шахматная доска под силуэтом
    cell = 56
    start = (SIZE - cell * 4) // 2
    for row in range(4):
        for col in range(4):
            if (row + col) % 2 == 0:
                x = start + col * cell
                y = start + row * cell
                draw.rectangle((x, y, x + cell, y + cell), fill=(120, 190, 235, 38))

    # конь (стилизованный силуэт)
    knight = [
        (150, 360), (170, 300), (200, 250), (215, 190), (250, 130),
        (285, 105), (300, 70), (330, 60), (315, 100), (335, 120),
        (320, 150), (345, 170), (330, 200), (300, 215), (315, 250),
        (355, 300), (380, 360),
    ]
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.polygon(knight, fill=(102, 192, 244, 150))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    image.alpha_composite(glow)
    draw = ImageDraw.Draw(image)
    draw.polygon(knight, fill=(232, 241, 250, 255))
    draw.line(knight + [knight[0]], fill=(70, 130, 180, 255), width=7, joint="curve")

    # глаз
    draw.ellipse((285, 138, 300, 153), fill=(25, 40, 55, 255))

    # рамка
    draw.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=64,
                           outline=(102, 192, 244, 220), width=8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    print(f"иконка: {OUT}")


if __name__ == "__main__":
    main()
