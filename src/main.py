#!/usr/bin/env python3
"""Точка входа chess.skay."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from chess_app import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("chess.skay")
    app.setOrganizationName("skayinray")
    resources = Path(__file__).resolve().parent / "resources"
    icon_path = resources / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    # Шрифты кладём в AppImage, чтобы текст выглядел одинаково на любой системе.
    for name in (
        "NotoSans-Regular.ttf",
        "NotoSans-Bold.ttf",
        "NotoSansMono-Regular.ttf",
        "NotoSansMono-Bold.ttf",
        "NotoSansSymbols2-Regular.ttf",
    ):
        font_path = resources / name
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
