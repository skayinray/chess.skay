"""Диалоги chess.skay: новая партия, превращение, о программе."""

from __future__ import annotations

import chess
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
)

from board_widget import piece_pixmap


class PromotionDialog(QDialog):
    def __init__(self, color: chess.Color, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Превращение пешки")
        self.setModal(True)
        self.chosen: chess.PieceType | None = None
        layout = QVBoxLayout(self)
        label = QLabel("Выберите фигуру:")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        row = QHBoxLayout()
        group = QButtonGroup(self)
        for piece in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            button = QPushButton()
            button.setIcon(QIcon(piece_pixmap(color, piece)))
            button.setIconSize(QSize(70, 70))
            button.setFixedSize(84, 84)
            button.setToolTip(chess.piece_name(piece))
            button.setStyleSheet(
                "QPushButton { background: #23303f; color: %s; border: 2px solid #3d5570;"
                " border-radius: 8px; } QPushButton:hover { border-color: #66c0f4; }"
                % ("#f4f9ff" if color == chess.WHITE else "#0d1118")
            )
            button.clicked.connect(lambda _=False, p=piece: self._pick(p))
            group.addButton(button)
            row.addWidget(button)
        layout.addLayout(row)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)

    def _pick(self, piece: chess.PieceType) -> None:
        self.chosen = piece
        self.accept()


class NewGameDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новая партия")
        self.setModal(True)
        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        self.ai_radio = QRadioButton("Против компьютера")
        self.ai_radio.setChecked(True)
        self.human_radio = QRadioButton("Два игрока")
        mode_row.addWidget(self.ai_radio)
        mode_row.addWidget(self.human_radio)
        layout.addLayout(mode_row)

        form = QFormLayout()
        self.color_combo = QComboBox()
        self.color_combo.addItems(["Белыми", "Чёрными", "Случайно"])
        form.addRow("Играю:", self.color_combo)

        self.difficulty = QComboBox()
        self.difficulty.addItems([
            "Новичок", "Клубный игрок", "Мастер", "Гроссмейстер",
        ])
        self.difficulty.setCurrentIndex(1)
        form.addRow("Сложность:", self.difficulty)

        self.time_combo = QComboBox()
        self.time_combo.addItems([
            "Без часов", "3 минуты", "5 минут", "10 минут",
            "15 минут", "5+3", "10+5", "15+10",
        ])
        self.time_combo.setCurrentIndex(3)
        form.addRow("Время:", self.time_combo)

        self.custom_check = QPushButton("Своё время…")
        self.custom_check.setCheckable(True)
        self.custom_row = QHBoxLayout()
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 180)
        self.minutes.setValue(10)
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 60)
        self.seconds.setValue(0)
        self.custom_row.addWidget(QLabel("Минут:"))
        self.custom_row.addWidget(self.minutes)
        self.custom_row.addWidget(QLabel("Прибавка, сек:"))
        self.custom_row.addWidget(self.seconds)
        form.addRow(self.custom_check, self.custom_row)
        layout.addLayout(form)

        note = QLabel("Подсказка: ход можно сделать кликом или перетаскиванием.")
        note.setStyleSheet("color: #7d90a5; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Начать")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> dict:
        vs_ai = self.ai_radio.isChecked()
        color_idx = self.color_combo.currentIndex()
        color = "random" if color_idx == 2 else ("white" if color_idx == 0 else "black")
        levels = ["easy", "medium", "hard", "expert"]
        custom = self.custom_check.isChecked()
        if custom:
            initial, increment = self.minutes.value() * 60, self.seconds.value()
        else:
            presets = {
                0: (0, 0), 1: (180, 0), 2: (300, 0), 3: (600, 0),
                4: (900, 0), 5: (300, 3), 6: (600, 5), 7: (900, 10),
            }
            initial, increment = presets[self.time_combo.currentIndex()]
        return {
            "vs_ai": vs_ai,
            "color": color,
            "difficulty": levels[self.difficulty.currentIndex()],
            "initial": initial,
            "increment": increment,
        }


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("О chess.skay")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        title = QLabel("<h1 style='margin:0;'>chess.skay</h1>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Шахматы с собственным движком, подсказками и часами")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7d90a5;")
        layout.addWidget(subtitle)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        text = QLabel(
            "<p>Полные правила шахмат: рокировка, взятие на проходе, превращение, "
            "объявленный мат и ничьи.</p>"
            "<p>Собственный движок на Python: минимакс с alpha-beta, таблица "
            "перестановок, четыре уровня сложности. Внешние программы не нужны.</p>"
            "<p>Подсказка, пре-мувы, часы с прибавкой, четыре темы доски, "
            "сохранение партии.</p>"
            "<p>Автор: <a href='https://github.com/skayinray'>skayinray</a></p>"
            "<p>Исходный код: <a href='https://github.com/skayinray/chess.skay'>"
            "github.com/skayinray/chess.skay</a></p>"
        )
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        layout.addWidget(text)

        close = QPushButton("Понятно")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignCenter)
