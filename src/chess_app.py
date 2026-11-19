"""chess.skay — главное окно и игровая логика."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import chess
import chess.pgn
from PySide6.QtCore import (
    Q_ARG, QMetaObject, QObject, QRectF, Qt, QThread, QTimer, Signal, Slot, QUrl,
)
from PySide6.QtGui import (
    QBrush, QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPen, QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMenuBar, QMessageBox, QPushButton, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from board_widget import (
    THEMES, ChessBoard, piece_file, piece_pixmap, set_piece_set, sized_piece_pixmap,
)
from dialogs import AboutDialog, NewGameDialog, PromotionDialog
from engine import choose_move


CONFIG_ROOT = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
CONFIG_DIR = CONFIG_ROOT / "chess.skay"
LAST_GAME = CONFIG_DIR / "last_game.json"
RATINGS_FILE = CONFIG_DIR / "ratings.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
THEME_TITLES = {
    "chesscom": "chess.com (зелёная)",
    "wood": "Дерево",
    "slate": "Стальной",
    "night": "Ночная",
    "emerald": "Изумруд",
}
DEFAULT_ELO = 1200
AI_ELO = {"easy": 900, "medium": 1300, "hard": 1700, "expert": 2100}


def clock_text(ms: int) -> str:
    ms = max(0, int(ms))
    minutes, rest = divmod(ms // 1000, 60)
    return f"{minutes:02d}:{rest:02d}"


class AiWorker(QObject):
    resultReady = Signal(object)
    hintReady = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.board = chess.Board()
        self.hint_board = chess.Board()
        self.level = "medium"
        self.cancelled = False
        self.hint_cancelled = False

    @Slot()
    def think(self) -> None:
        try:
            result = choose_move(self.board, self.level, lambda: self.cancelled)
            if not self.cancelled:
                self.resultReady.emit(result)
        except Exception:  # pragma: no cover - защита потока
            self.resultReady.emit(None)

    @Slot()
    def hint(self) -> None:
        """Подсказка считается в том же фоновом потоке — без фриза интерфейса."""
        try:
            result = choose_move(self.hint_board, "hard", lambda: self.hint_cancelled)
            if not self.hint_cancelled:
                self.hintReady.emit(result)
        except Exception:  # pragma: no cover - защита потока
            self.hintReady.emit(None)


class EvalBar(QWidget):
    """Вертикальная полоса оценки, как на шахматных сайтах."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.score = 0
        self.setFixedWidth(18)
        self.setMinimumHeight(120)

    def set_score(self, score: int) -> None:
        self.score = score
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.fillRect(rect, QColor("#1b222c"))
        norm = max(-1.0, min(1.0, self.score / 800.0))
        frac = abs(norm)
        h = rect.height() * frac
        if norm >= 0:
            top = rect.height() - h
            color = QColor("#e9f1f8")
        else:
            top = 0.0
            color = QColor("#141a22")
        painter.fillRect(QRectF(0, top, rect.width(), h), color)
        pen = QPen(QColor("#3a4859"), 1)
        painter.setPen(pen)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        painter.end()


class CapturedRow(QWidget):
    """Захваченные фигуры — только сами фигуры, без каких-либо плашек."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pieces: list[tuple[chess.Color, chess.PieceType]] = []
        self.setFixedHeight(26)

    def set_pieces(self, pieces: list[tuple[chess.Color, chess.PieceType]]) -> None:
        self.pieces = pieces
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        dpr = self.devicePixelRatioF()
        x = 0.0
        for color, piece_type in self.pieces:
            rect = QRectF(x, 1, 24, 24)
            pixmap = sized_piece_pixmap(color, piece_type, 24, dpr)
            if not pixmap.isNull():
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
            x += 25
        painter.end()


class PlayerCard(QFrame):
    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self.avatar = QLabel(name[:1])
        self.avatar.setFixedSize(38, 38)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setObjectName("avatar")

        self.name_label = QLabel(name)
        self.name_label.setObjectName("playerName")
        self.rating_label = QLabel("1200")
        self.rating_label.setObjectName("playerRating")
        self.clock = QLabel("10:00")
        self.clock.setObjectName("playerClock")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.captured = CapturedRow()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 7)
        layout.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.avatar)
        middle = QVBoxLayout()
        middle.setSpacing(0)
        line = QHBoxLayout()
        line.setSpacing(7)
        line.addWidget(self.name_label)
        line.addWidget(self.rating_label)
        line.addStretch(1)
        middle.addLayout(line)
        middle.addWidget(self.captured)
        top.addLayout(middle, 1)
        top.addWidget(self.clock)
        layout.addLayout(top)
        self.set_active(False)

    def set_active(self, active: bool, low: bool = False) -> None:
        # unpolish/polish 10 раз в секунду (каждый тик часов) заставлял Qt
        # пересчитывать стиль всего окна — меняем только при реальной смене.
        name = "activePlayer" if active else "playerCard"
        if self.objectName() != name:
            self.setObjectName(name)
            self.style().unpolish(self)
            self.style().polish(self)
        clock_name = "lowClock" if low else ("activeClock" if active else "playerClock")
        if self.clock.objectName() != clock_name:
            self.clock.setObjectName(clock_name)
            self.clock.style().unpolish(self.clock)
            self.clock.style().polish(self.clock)

    def set_captured(self, pieces: list[tuple[chess.Color, chess.PieceType]]) -> None:
        self.captured.set_pieces(pieces)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("chess.skay")
        self.setMinimumSize(1040, 720)
        self.resize(1240, 820)

        self.board = chess.Board()
        self.move_stack: list[chess.Move] = []
        self.san_stack: list[str] = []
        self.clock_history: list[tuple[int, int]] = []
        self.redo_stack: list[tuple[chess.Move, str, tuple[int, int]]] = []
        self.vs_ai = True
        self.player_color = chess.WHITE
        self.difficulty = "medium"
        self.initial_time = 600_000
        self.increment = 0
        self.clocks = {chess.WHITE: 600_000, chess.BLACK: 600_000}
        self.game_over = False
        self.result_text = ""
        self.flipped = False
        settings = self._load_settings()
        self.theme = settings.get("theme", "chesscom")
        if self.theme not in THEMES:
            self.theme = "chesscom"
        self.last_tick = time.monotonic()
        self.ai_pending = False
        self.player_elo = DEFAULT_ELO
        self.ratings = {"white": DEFAULT_ELO, "black": DEFAULT_ELO}
        self.rating_applied = False
        self._load_ratings()
        self.premove: chess.Move | None = None

        self._build_ui()
        self._apply_style()
        self._setup_ai()
        self._setup_clock()

        self.board_widget.set_board(self.board)
        self.board_widget.set_theme(self.theme)
        self.board_widget.promotion_chooser = self._choose_promotion
        self._update_all()
        QTimer.singleShot(200, self._load_last_game)

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.view_stack = QStackedWidget()
        root.addWidget(self.view_stack)

        self.menu_widget = self._build_main_menu()
        self.view_stack.addWidget(self.menu_widget)

        self.game_widget = QWidget()
        self.game_widget.setObjectName("gamePage")
        self.view_stack.addWidget(self.game_widget)
        game_root = QVBoxLayout(self.game_widget)
        game_root.setContentsMargins(0, 0, 0, 0)
        game_root.setSpacing(0)

        header = QFrame()
        header.setObjectName("gameHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 11, 22, 11)
        brand = QLabel("chess.skay")
        brand.setObjectName("brandLabel")
        header_layout.addWidget(brand)
        header_layout.addStretch(1)
        header_hint = QLabel("Клик или перетаскивание   ·   ПКМ — снять пре-мув   ·   Ctrl+Z — отмена   ·   H — подсказка")
        header_hint.setObjectName("hintLabel")
        header_layout.addWidget(header_hint)
        game_root.addWidget(header)

        content = QWidget()
        content.setObjectName("gameContent")
        game_root.addWidget(content)
        root_layout = QHBoxLayout(content)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(16)

        board_col = QVBoxLayout()
        board_col.setSpacing(9)
        self.top_card = PlayerCard("Чёрные")
        self.bottom_card = PlayerCard("Белые")
        self.board_widget = ChessBoard()
        self.board_widget.moveMade.connect(self.on_move)
        self.board_widget.premoveMade.connect(self.on_premove)
        self.board_widget.premoveCancelled.connect(self.on_premove_cancelled)
        board_col.addWidget(self.top_card)
        board_row = QHBoxLayout()
        board_row.setSpacing(9)
        self.eval_bar = EvalBar()
        board_row.addWidget(self.eval_bar)
        # Без stretch: доска квадратная и прижата к полосе оценки,
        # а не «плавает» в середине широкого виджета.
        board_row.addWidget(self.board_widget)
        board_col.addLayout(board_row, 1)
        board_col.addWidget(self.bottom_card)
        root_layout.addLayout(board_col, 1)

        side_frame = QFrame()
        side_frame.setObjectName("sidePanel")
        side = QVBoxLayout(side_frame)
        side.setSpacing(11)
        side.setContentsMargins(16, 16, 16, 14)

        self.status = QLabel("Ход белых")
        self.status.setObjectName("statusLabel")
        side.addWidget(self.status)
        self.thinking = QLabel("")
        self.thinking.setObjectName("thinkingLabel")
        side.addWidget(self.thinking)

        moves_title = QLabel("ПАРТИЯ")
        moves_title.setObjectName("sectionTitle")
        side.addWidget(moves_title)
        self.moves_list = QTableWidget(0, 3)
        self.moves_list.setObjectName("movesTable")
        self.moves_list.setHorizontalHeaderLabels(["№", "Белые", "Чёрные"])
        self.moves_list.verticalHeader().setVisible(False)
        self.moves_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.moves_list.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        # Убираем прямоугольник фокуса/выделения поверх текста ходов.
        self.moves_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.moves_list.setAlternatingRowColors(False)
        self.moves_list.horizontalHeader().setStretchLastSection(True)
        self.moves_list.setColumnWidth(0, 44)
        self.moves_list.setColumnWidth(1, 110)
        self.moves_list.setFont(QFont("Noto Sans Mono", 13))
        side.addWidget(self.moves_list, 1)

        self.eval_label = QLabel("Материал: +0.0")
        self.eval_label.setObjectName("evalLabel")
        side.addWidget(self.eval_label)

        buttons = [
            ("Подсказка", self.show_hint),
            ("Отмена хода", self.undo_move),
            ("Повторить", self.redo_move),
            ("Перевернуть доску", self.toggle_flip),
            ("Тема доски", self.cycle_theme),
            ("Новая партия", self.new_game),
            ("Главное меню", self.show_main_menu),
            ("Сдаться", self.resign),
        ]
        grid = QGridLayout()
        grid.setSpacing(7)
        for index, (text, callback) in enumerate(buttons):
            button = QPushButton(text)
            button.setObjectName("primaryButton" if text in
                                 ("Новая партия", "Главное меню") else "sideButton")
            button.clicked.connect(callback)
            grid.addWidget(button, index // 2, index % 2)
        side.addLayout(grid)

        root_layout.addWidget(side_frame, 0)
        self.side_layout = side

        for sequence, callback in (
            ("Ctrl+Z", self.undo_move),
            ("Ctrl+Y", self.redo_move),
            ("Ctrl+N", self.new_game),
            ("F", self.toggle_flip),
            ("H", self.show_hint),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

        self._build_menu()
        self.view_stack.setCurrentWidget(self.menu_widget)
        self.menuBar().setVisible(False)
        self.continue_button.setEnabled(LAST_GAME.exists())
        self._refresh_ratings()

    def _build_main_menu(self) -> QWidget:
        page = QWidget()
        page.setObjectName("mainMenu")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        title = QLabel("chess.skay")
        title.setObjectName("menuTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Шахматы, в которые хочется играть")
        subtitle.setObjectName("menuSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        self.menu_rating = QLabel("Ваш рейтинг: 1200")
        self.menu_rating.setObjectName("menuRating")
        self.menu_rating.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.menu_rating)

        pieces = QHBoxLayout()
        pieces.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.menu_piece_labels: list[tuple[QLabel, str]] = []
        for code in ("bR", "bN", "bB", "bQ", "bK", "bP", "wP", "wK", "wQ", "wB", "wN", "wR"):
            label = QLabel()
            pixmap = QPixmap(piece_file(code))
            label.setPixmap(pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
            self.menu_piece_labels.append((label, code))
            pieces.addWidget(label)
        layout.addLayout(pieces)
        layout.addSpacing(22)

        entries = [
            ("Играть с компьютером", self.start_vs_ai, "menuButton"),
            ("Игра с другом (2 игрока)", self.start_two_players, "menuButton"),
            ("Продолжить партию", self.continue_game, "menuButton"),
            (f"Тема доски: {THEME_TITLES[self.theme]}", self.cycle_theme, "menuButton"),
            ("О программе", lambda: AboutDialog(self).exec(), "menuButton"),
            ("Выход", self.close, "menuButton"),
        ]
        for text, callback, object_name in entries:
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.clicked.connect(callback)
            if text == "Продолжить партию":
                self.continue_button = button
            if callback == self.cycle_theme:
                self.theme_button = button
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)

        footer = QLabel("автор: skayinray  •  github.com/skayinray")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color:#4d6276; font-size:11px; margin-top:18px;")
        layout.addWidget(footer)
        return page

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        game = menubar.addMenu("Партия")
        game.addAction("Главное меню", self.show_main_menu)
        game.addAction("Новая партия…", self.new_game)
        game.addAction("Сохранить PGN…", self.save_pgn)
        game.addAction("Загрузить PGN…", self.load_pgn)
        game.addSeparator()
        game.addAction("Выход", self.close)

        view = menubar.addMenu("Вид")
        theme_menu = view.addMenu("Тема доски")
        for key, title in THEME_TITLES.items():
            action = theme_menu.addAction(title, lambda k=key: self.set_theme(k))
            action.setCheckable(True)
            action.setChecked(key == self.theme)
            action.setData(key)
        view.addSeparator()
        view.addAction("Перевернуть доску", self.toggle_flip)
        pieces_menu = view.addMenu("Стиль фигур")
        for key, title in (("chesscom", "chess.com (neo)"), ("classic", "Классика")):
            action = pieces_menu.addAction(title, lambda k=key: self.set_piece_style(k))
            action.setCheckable(True)
            action.setChecked(key == "chesscom")
            action.setData(key)

        help_menu = menubar.addMenu("Справка")
        help_menu.addAction("О программе", lambda: AboutDialog(self).exec())
        help_menu.addAction("GitHub автора (skayinray)", lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/skayinray")))

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget#centralWidget, QWidget#gamePage,
            QWidget#gameContent { background:#0d1219; color:#dce6f0;
                font-family:'Noto Sans'; font-size:13px; }
            /* Никаких прямоугольников под отдельными надписями. */
            QLabel { background: transparent; }
            QMenuBar { background:#131c27; border-bottom:1px solid #2a3b4e;
                font-size:13px; }
            QMenuBar::item { padding:7px 14px; }
            QMenuBar::item:selected { background:#2b5f85; }
            QMenu { background:#1a2533; border:1px solid #3a4e64; font-size:13px; }
            QMenu::item { padding:7px 20px; }
            QMenu::item:selected { background:#2b5f85; }

            QFrame#gameHeader { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #1a2b3e, stop:1 #121d2a); border-bottom:1px solid #34567a; }
            QLabel#brandLabel { color:#f0f6fc; font-size:23px; font-weight:bold;
                letter-spacing:1px; }
            QLabel#hintLabel { color:#8499ae; font-size:12px; }

            QFrame#sidePanel { background:#151e2a; border:1px solid #2a3b4f;
                border-radius:12px; }
            QLabel#statusLabel { color:#7fc4f5; font-size:18px; font-weight:bold;
                padding:2px 0 0 0; }
            QLabel#statusCheck { color:#ff8a8a; font-size:18px; font-weight:bold; }
            QLabel#statusOver { color:#ffc273; font-size:18px; font-weight:bold; }
            QLabel#thinkingLabel { color:#8fa6bd; font-size:12px; min-height:18px; }
            QLabel#sectionTitle { color:#728aa2; font-size:11px; font-weight:bold;
                letter-spacing:2px; margin-top:4px; }
            QLabel#evalLabel { color:#9fb3c8; font-size:12px; }

            QTableWidget { background:#101823; border:1px solid #2a3b4f;
                border-radius:8px; gridline-color:#202d3c; outline:none; }
            QTableWidget::item { padding:5px 8px; border:0; outline:none; }
            QTableWidget::item:focus { border:0; outline:none; }
            QAbstractButton:focus { outline:none; }
            QHeaderView::section { background:#1c2838; color:#8fa6bd;
                border:0; border-bottom:1px solid #2a3b4f; padding:7px 8px;
                font-size:12px; font-weight:bold; }

            QFrame#playerCard, QFrame#activePlayer { background:#17212e;
                border:1px solid #2b3d52; border-radius:10px; }
            QFrame#activePlayer { background:#1c3448; border-color:#5aa9e6; }
            QLabel#avatar { background:#2a4259; color:#dce9f5; border-radius:19px;
                font-size:16px; font-weight:bold; }
            QFrame#activePlayer QLabel#avatar { background:#3a7fb0; color:#ffffff; }
            QLabel#playerName { color:#eef4fa; font-size:15px; font-weight:bold; }
            QLabel#playerRating { color:#8fb6d8; font-size:12px; }
            QLabel#playerClock { color:#e8f1fa; font-size:26px; font-weight:bold;
                font-family:'Noto Sans Mono'; min-width:92px; }
            QLabel#activeClock { color:#eaf6ff; font-size:26px; font-weight:bold;
                font-family:'Noto Sans Mono'; min-width:92px; }
            QLabel#lowClock { color:#ff7b7b; font-size:26px; font-weight:bold;
                font-family:'Noto Sans Mono'; min-width:92px; }

            QPushButton { background:#1c2838; color:#dce6f0; border:1px solid #354a60;
                border-radius:7px; padding:8px 12px; font-size:13px; }
            QPushButton:hover { background:#27405a; border-color:#66c0f4; }
            QPushButton:pressed { background:#15202d; }
            QPushButton:checked { background:#1e3a2c; border-color:#63c98c;
                color:#b6ecc9; }
            QPushButton#primaryButton { background:#245774; border-color:#3f8fbc;
                font-weight:bold; }
            QPushButton#primaryButton:hover { background:#30739a; border-color:#7fd0ff; }
            QPushButton#sideButton { background:#1b2635; border-color:#304357; }

            QWidget#mainMenu { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #182534, stop:1 #0a0f16); }
            QLabel#menuTitle { color:#f2f8ff; font-size:62px; font-weight:bold;
                letter-spacing:2px; }
            QLabel#menuSubtitle { color:#8fa6bd; font-size:17px; margin-bottom:8px; }
            QLabel#menuRating { color:#7fc4f5; font-size:15px; margin-bottom:18px; }
            QPushButton#menuButton { background:#1e2d3f; color:#e8f1fa;
                border:1px solid #42617e; border-radius:11px;
                font-size:16px; min-width:330px; padding:13px 18px; }
            QPushButton#menuButton:hover { background:#2b5f85; border-color:#7fd0ff; }
            QPushButton#menuButton:disabled { color:#5c6c7d; border-color:#2a3644; }
        """)

    def _setup_ai(self) -> None:
        self.ai_thread = QThread(self)
        self.ai_worker = AiWorker()
        self.ai_worker.moveToThread(self.ai_thread)
        self.ai_worker.resultReady.connect(self.on_ai_result)
        self.ai_worker.hintReady.connect(self.on_hint_result)
        self.ai_thread.start()

    def _setup_clock(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(100)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start()
        # Держим доску строго квадратной независимо от момента расчёта layout.
        self.board_sync_timer = QTimer(self)
        self.board_sync_timer.setInterval(120)
        self.board_sync_timer.timeout.connect(self._sync_board_width)
        self.board_sync_timer.start()

    def _sync_board_width(self) -> None:
        board = getattr(self, "board_widget", None)
        if board is None:
            return
        side = board.height()
        if side >= board.minimumWidth() and board.width() != side:
            board.setFixedWidth(side)

    # ---------------------------------------------------------------- rating --

    def _load_ratings(self) -> None:
        try:
            data = json.loads(RATINGS_FILE.read_text(encoding="utf-8"))
            self.player_elo = int(data.get("player", DEFAULT_ELO))
        except (OSError, ValueError, TypeError):
            self.player_elo = DEFAULT_ELO

    def _save_ratings(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            RATINGS_FILE.write_text(json.dumps({"player": self.player_elo}), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _load_settings() -> dict:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _save_settings(data: dict) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _refresh_ratings(self) -> None:
        ai_elo = AI_ELO.get(self.difficulty, 1300)
        if self.vs_ai:
            if self.player_color == chess.WHITE:
                self.ratings = {"white": self.player_elo, "black": ai_elo}
            else:
                self.ratings = {"white": ai_elo, "black": self.player_elo}
        else:
            self.ratings = {"white": self.player_elo, "black": self.player_elo}
        if hasattr(self, "top_card"):
            self.top_card.rating_label.setText(str(self.ratings["black"]))
            self.bottom_card.rating_label.setText(str(self.ratings["white"]))
        if hasattr(self, "menu_rating"):
            self.menu_rating.setText(f"Ваш рейтинг: {self.player_elo}")

    def _white_score(self) -> float:
        board = self.board
        if board.is_checkmate():
            return 0.0 if board.turn == chess.WHITE else 1.0
        text = self.result_text
        if "Ничья" in text:
            return 0.5
        if "Победа: Белые" in text or "сдались" in text and text.startswith("Чёрные"):
            return 1.0
        if "Победа: Чёрные" in text or "сдались" in text and text.startswith("Белые"):
            return 0.0
        if "превысили лимит" in text:
            return 0.0 if text.startswith("Белые") else 1.0
        return 0.5

    def _apply_game_rating(self) -> None:
        if self.rating_applied or not self.game_over:
            return
        self.rating_applied = True
        score = self._white_score()
        opponent = AI_ELO.get(self.difficulty, 1300) if self.vs_ai else self.player_elo
        expected = 1.0 / (1.0 + 10.0 ** ((opponent - self.player_elo) / 400.0))
        actual = score if self.player_color == chess.WHITE else 1.0 - score
        delta = round(32 * (actual - expected))
        self.player_elo = max(100, self.player_elo + delta)
        self._save_ratings()
        self._refresh_ratings()

    # --------------------------------------------------------- game actions --

    def show_main_menu(self) -> None:
        self._save_last_game()
        self._clear_premove()
        self.ai_worker.cancelled = True
        self.ai_pending = False
        self.thinking.setText("")
        self.menuBar().setVisible(False)
        self.view_stack.setCurrentWidget(self.menu_widget)
        self.continue_button.setEnabled(LAST_GAME.exists())
        self._refresh_ratings()

    def _show_game(self) -> None:
        self.last_tick = time.monotonic()
        self.menuBar().setVisible(True)
        self.view_stack.setCurrentWidget(self.game_widget)

    def start_vs_ai(self) -> None:
        dialog = NewGameDialog(self)
        dialog.ai_radio.setChecked(True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_with_settings(dialog.settings())

    def start_two_players(self) -> None:
        dialog = NewGameDialog(self)
        dialog.human_radio.setChecked(True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_with_settings(dialog.settings())

    def continue_game(self) -> None:
        if not LAST_GAME.exists():
            return
        self._load_last_game()
        self._show_game()

    def cycle_theme(self) -> None:
        keys = list(THEMES)
        self.set_theme(keys[(keys.index(self.theme) + 1) % len(keys)])

    def new_game(self) -> None:
        dialog = NewGameDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_with_settings(dialog.settings())

    def _start_with_settings(self, settings: dict) -> None:
        self.vs_ai = settings["vs_ai"]
        self.difficulty = settings["difficulty"]
        self.initial_time = settings["initial"] * 1000
        self.increment = settings["increment"] * 1000
        color = settings["color"]
        if color == "random":
            import random
            color = "white" if random.random() < 0.5 else "black"
        self.player_color = chess.WHITE if color == "white" else chess.BLACK
        if not self.vs_ai:
            self.player_color = chess.WHITE

        self.board = chess.Board()
        self.move_stack.clear()
        self.san_stack.clear()
        self.clock_history.clear()
        self.redo_stack.clear()
        self.clocks = {chess.WHITE: self.initial_time, chess.BLACK: self.initial_time}
        self.game_over = False
        self.result_text = ""
        self.rating_applied = False
        self._clear_premove()
        self.last_tick = time.monotonic()
        self.flipped = self.player_color == chess.BLACK
        self.board_widget.set_flipped(self.flipped)
        self.board_widget.set_hint(None)
        self.board_widget.set_board(self.board)
        self.board_widget.set_last_move(None)
        self._refresh_ratings()
        self._update_all()
        self._save_last_game()
        self._show_game()
        if self.vs_ai and self.board.turn != self.player_color:
            self._request_ai()

    def _update_premove_mode(self) -> None:
        """Пока ход не нашей стороны, разрешаем планировать свой ход."""
        # Pre-moves имеют смысл только против компьютера: в режиме двух
        # игроков оба хода делаются вручную.
        if not self.vs_ai or self.game_over or self.board.turn == self.player_color:
            self.board_widget.set_premove_mode(None)
        else:
            self.board_widget.set_premove_mode(self.player_color)

    @Slot(object)
    def on_premove(self, move: chess.Move) -> None:
        if self.game_over:
            return
        self.premove = move
        self.board_widget.set_premove(move)
        self._update_status()

    @Slot()
    def on_premove_cancelled(self) -> None:
        self.premove = None
        self._update_status()

    def _clear_premove(self) -> None:
        self.premove = None
        self.board_widget.set_premove(None)
        self.board_widget.set_premove_mode(None)

    def _apply_premove(self) -> None:
        """Применить запланированный ход, если он всё ещё законен."""
        if self.premove is None or self.game_over:
            self._update_premove_mode()
            return
        move = self.premove
        self.premove = None
        self.board_widget.set_premove(None)
        if move not in self.board.legal_moves:
            self.thinking.setText("Пре-мув отменён: ход стал невозможен")
            self._update_premove_mode()
            return
        self._play_move(move)

    def on_move(self, move: chess.Move) -> None:
        if self.game_over or self.ai_pending:
            return
        if self.vs_ai and self.board.turn != self.player_color:
            return
        if move not in self.board.legal_moves:
            return
        self._play_move(move)

    def _play_move(self, move: chess.Move, from_ai: bool = False) -> None:
        if not from_ai and self.premove is not None:
            # Игрок решил сходить сразу — запланированный ход больше не нужен.
            self.premove = None
            self.board_widget.set_premove(None)
        san = self.board.san(move)
        mover = self.board.turn
        self.clock_history.append((self.clocks[chess.WHITE], self.clocks[chess.BLACK]))
        self.board_widget.prepare_animation(self.board, move)
        self.board.push(move)
        self.move_stack.append(move)
        self.san_stack.append(san)
        self.clocks[mover] += self.increment
        if not from_ai:
            self.redo_stack.clear()
            self.board_widget.set_hint(None)
            self.thinking.setText("")
        self.board_widget.set_last_move(move, animate=True)
        self._check_game_over()
        self._update_all()
        self._save_last_game()
        self._update_premove_mode()
        if self.game_over:
            return
        if self.premove is not None:
            # Даем анимации ответного хода коротко показаться, затем летит пре-мув.
            QTimer.singleShot(120, self._apply_premove)
        elif self.vs_ai and self.board.turn != self.player_color:
            QTimer.singleShot(370, self._request_ai)

    def _request_ai(self) -> None:
        if self.game_over or self.ai_pending:
            return
        self.ai_pending = True
        self.ai_worker.cancelled = False
        self.ai_worker.board = self.board.copy(stack=False)
        self.ai_worker.level = self.difficulty
        self.thinking.setText("Компьютер думает…")
        self._update_premove_mode()
        QMetaObject.invokeMethod(self.ai_worker, "think", Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def on_ai_result(self, result) -> None:
        self.ai_pending = False
        if result is None or self.game_over:
            return
        move = result.move
        if move is None or move not in self.board.legal_moves:
            return
        self.thinking.setText("")
        self._play_move(move, from_ai=True)

    def _check_game_over(self) -> None:
        board = self.board
        if board.is_checkmate():
            winner = "Белые" if board.turn == chess.BLACK else "Чёрные"
            self.game_over = True
            self.result_text = f"Мат. Победа: {winner}"
        elif board.is_stalemate():
            self.game_over, self.result_text = True, "Ничья: пат"
        elif board.is_insufficient_material():
            self.game_over, self.result_text = True, "Ничья: недостаточно материала"
        elif board.is_fifty_moves():
            self.game_over, self.result_text = True, "Ничья: правило 50 ходов"
        elif board.is_repetition(3):
            self.game_over, self.result_text = True, "Ничья: троекратное повторение"
        elif board.is_seventyfive_moves():
            self.game_over, self.result_text = True, "Ничья: правило 75 ходов"
        if self.game_over:
            self._apply_game_rating()

    def undo_move(self) -> None:
        if self.ai_pending or not self.move_stack:
            return
        count = 2 if (self.vs_ai and self.board.turn == self.player_color
                      and len(self.move_stack) >= 2) else 1
        for _ in range(count):
            if not self.move_stack:
                break
            move = self.move_stack.pop()
            san = self.san_stack.pop()
            clocks = self.clock_history.pop() if self.clock_history else (self.initial_time, self.initial_time)
            self.clocks = {chess.WHITE: clocks[0], chess.BLACK: clocks[1]}
            self.redo_stack.append((move, san, clocks))
            self.board.pop()
        self.game_over = False
        self.result_text = ""
        self._clear_premove()
        self.board_widget.set_board(self.board)
        self.board_widget.set_last_move(self.move_stack[-1] if self.move_stack else None)
        self.board_widget.set_hint(None)
        self._update_all()
        self._save_last_game()

    def redo_move(self) -> None:
        if self.ai_pending or not self.redo_stack:
            return
        move, san, clocks = self.redo_stack.pop()
        self.clock_history.append((self.clocks[chess.WHITE], self.clocks[chess.BLACK]))
        self.clocks = {chess.WHITE: clocks[0], chess.BLACK: clocks[1]}
        self.board_widget.prepare_animation(self.board, move)
        self.board.push(move)
        self.move_stack.append(move)
        self.san_stack.append(san)
        self.board_widget.set_last_move(move, animate=True)
        self.game_over = False
        self.result_text = ""
        self._clear_premove()
        self._check_game_over()
        self._update_all()
        self._save_last_game()

    def resign(self) -> None:
        if self.game_over or not self.move_stack:
            return
        side = "Белые" if self.board.turn == chess.WHITE else "Чёрные"
        self.game_over = True
        self.result_text = f"{side} сдались"
        self._apply_game_rating()
        self._update_status()

    def show_hint(self) -> None:
        """Подсказка считается в фоновом потоке — интерфейс не замирает."""
        if self.game_over or self.ai_pending or self.view_stack.currentWidget() is not self.game_widget:
            return
        self.thinking.setText("Ищу лучший ход…")
        self.ai_worker.hint_cancelled = False
        self.ai_worker.hint_board = self.board.copy(stack=False)
        QMetaObject.invokeMethod(self.ai_worker, "hint", Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def on_hint_result(self, result) -> None:
        self.thinking.setText("")
        if result and result.move and result.move in self.board.legal_moves:
            self.board_widget.set_hint(result.move)
            self.status.setText(f"Подсказка: {self.board.san(result.move)}")

    def toggle_flip(self) -> None:
        self.flipped = not self.flipped
        self.board_widget.set_flipped(self.flipped)

    def set_theme(self, key: str) -> None:
        if key not in THEMES:
            return
        self.theme = key
        self.board_widget.set_theme(key)
        # Галочки живут в подменю «Тема доски», а не среди пунктов «Вид».
        for action in self.menuBar().actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for item in submenu.actions():
                nested = item.menu()
                if nested is not None and nested.title() == "Тема доски":
                    for theme_action in nested.actions():
                        theme_action.setChecked(theme_action.data() == key)
        # Мгновенная обратная связь на главном экране: доска там не видна,
        # поэтому показываем выбранную тему прямо на кнопке.
        button = getattr(self, "theme_button", None)
        if button is not None:
            button.setText(f"Тема доски: {THEME_TITLES[key]}")
        settings = self._load_settings()
        settings["theme"] = key
        self._save_settings(settings)

    def set_piece_style(self, key: str) -> None:
        set_piece_set(key)
        self.board_widget.update()
        for label, code in getattr(self, "menu_piece_labels", []):
            pixmap = QPixmap(piece_file(code))
            label.setPixmap(pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        for action in self.menuBar().actions()[1].menu().actions():
            sub = action.menu()
            if sub is not None and sub.title() == "Стиль фигур":
                for item in sub.actions():
                    item.setChecked(item.data() == key)

    def _choose_promotion(self, color: chess.Color):
        dialog = PromotionDialog(color, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.chosen
        return None

    # --------------------------------------------------------------- clock --

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = (now - self.last_tick) * 1000
        self.last_tick = now
        if (self.game_over or self.initial_time == 0
                or self.view_stack.currentWidget() is self.menu_widget):
            return
        self.clocks[self.board.turn] = max(0, self.clocks[self.board.turn] - elapsed)
        if self.clocks[self.board.turn] <= 0:
            loser = "Белые" if self.board.turn == chess.WHITE else "Чёрные"
            self.game_over = True
            self.result_text = f"{loser} превысили лимит времени"
            self._apply_game_rating()
            self._update_status()
        self._update_clocks()

    # -------------------------------------------------------------- display --

    def _update_all(self) -> None:
        self._update_clocks()
        self._update_status()
        self._update_moves()
        self._update_eval()
        self._update_captured()

    def _update_clocks(self) -> None:
        self.top_card.clock.setText(clock_text(self.clocks[chess.BLACK]))
        self.bottom_card.clock.setText(clock_text(self.clocks[chess.WHITE]))
        for card, color in ((self.top_card, chess.BLACK), (self.bottom_card, chess.WHITE)):
            low = self.clocks[color] < 30_000 and self.initial_time > 0
            card.set_active(self.board.turn == color and not self.game_over, low)

    def _update_status(self) -> None:
        name = "statusLabel"
        if self.game_over:
            self.status.setText(self.result_text)
            name = "statusOver"
        elif self.board.is_check():
            turn = "Белые" if self.board.turn == chess.WHITE else "Чёрные"
            self.status.setText(f"Шах! {turn}")
            name = "statusCheck"
        else:
            turn = "Белые" if self.board.turn == chess.WHITE else "Чёрные"
            if self.vs_ai:
                who = "вы" if self.board.turn == self.player_color else "компьютер"
                self.status.setText(f"Ход: {turn} ({who})")
            else:
                self.status.setText(f"Ход: {turn}")
        if self.premove is not None and not self.game_over:
            self.status.setText(self.status.text() + "   · пре-мув ждёт")
        self.status.setObjectName(name)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _update_moves(self) -> None:
        self.moves_list.setRowCount(0)
        for i in range(0, len(self.san_stack), 2):
            number = i // 2 + 1
            white = self.san_stack[i]
            black = self.san_stack[i + 1] if i + 1 < len(self.san_stack) else ""
            row = self.moves_list.rowCount()
            self.moves_list.insertRow(row)
            for col, value in enumerate((f"{number}.", white, black)):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                                      (Qt.AlignmentFlag.AlignRight if col == 0
                                       else Qt.AlignmentFlag.AlignLeft))
                self.moves_list.setItem(row, col, cell)
        self.moves_list.scrollToBottom()

    def _update_eval(self) -> None:
        from engine import evaluate
        score = evaluate(self.board)
        if self.board.turn == chess.BLACK:
            score = -score
        self.eval_bar.set_score(score)
        label = f"{score / 100:+.1f}"
        self.eval_label.setText(f"Материал: {label}")

    def _update_captured(self) -> None:
        initial = {
            chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2,
            chess.ROOK: 2, chess.QUEEN: 1,
        }
        for card, color in ((self.top_card, chess.BLACK), (self.bottom_card, chess.WHITE)):
            enemy = not color
            pieces: list[tuple[chess.Color, chess.PieceType]] = []
            for piece_type, count in initial.items():
                on_board = len(self.board.pieces(piece_type, enemy))
                missing = count - on_board
                pieces.extend([(color, piece_type)] * max(0, missing))
            card.set_captured(pieces)

    # ------------------------------------------------------------ persistence --

    def _save_last_game(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "fen": self.board.fen(),
                "moves": self.san_stack,
                "vs_ai": self.vs_ai,
                "player_color": "white" if self.player_color else "black",
                "difficulty": self.difficulty,
                "initial": self.initial_time // 1000,
                "increment": self.increment // 1000,
                "clocks": self.clocks,
            }
            LAST_GAME.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _load_last_game(self) -> None:
        if not LAST_GAME.exists():
            return
        try:
            data = json.loads(LAST_GAME.read_text(encoding="utf-8"))
            fen = data.get("fen")
            if not fen:
                return
            board = chess.Board(fen)
            saved_san = list(data.get("moves", []))
            # Восстанавливаем историю ходов из нотации: доска из FEN не несёт
            # move_stack, поэтому без этого отмена/повтор после перезапуска
            # работали бы некорректно.
            replay = chess.Board()
            moves: list[chess.Move] = []
            restored_san: list[str] = []
            for san in saved_san:
                try:
                    move = replay.parse_san(san)
                except Exception:
                    break
                moves.append(move)
                restored_san.append(replay.san(move))
                replay.push(move)
            self.board = replay
            self.move_stack = moves
            self.san_stack = restored_san
            self.vs_ai = data.get("vs_ai", True)
            self.player_color = chess.WHITE if data.get("player_color", "white") == "white" else chess.BLACK
            self.difficulty = data.get("difficulty", "medium")
            self.initial_time = int(data.get("initial", 600)) * 1000
            self.increment = int(data.get("increment", 0)) * 1000
            clocks = data.get("clocks", {})
            self.clocks = {
                chess.WHITE: int(clocks.get("True", self.initial_time)),
                chess.BLACK: int(clocks.get("False", self.initial_time)),
            }
            self.clock_history = [(self.clocks[chess.WHITE], self.clocks[chess.BLACK])] * len(self.move_stack)
            self.board_widget.set_board(self.board)
            self.board_widget.set_last_move(self.move_stack[-1] if self.move_stack else None)
            self.board_widget.set_flipped(self.player_color == chess.BLACK)
            self._clear_premove()
            self.rating_applied = True  # загруженная партия уже учтена
            self._check_game_over()
            self._clear_premove()
            self._refresh_ratings()
            self._update_all()
        except Exception:
            pass

    def save_pgn(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить PGN", "partia.pgn", "PGN (*.pgn)")
        if not path:
            return
        try:
            game = chess.pgn.Game.from_board(self.board)
            game.headers["White"] = "chess.skay"
            game.headers["Black"] = "Компьютер" if self.vs_ai else "Игрок"
            game.headers["Result"] = self.board.result()
            Path(path).write_text(str(game), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    def load_pgn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить PGN", "", "PGN (*.pgn)")
        if not path:
            return
        try:
            with Path(path).open(encoding="utf-8") as handle:
                game = chess.pgn.read_game(handle)
            if game is None:
                return
            board = chess.Board()
            for move in game.mainline_moves():
                board.push(move)
            self.board = board
            self.move_stack = list(board.move_stack)
            replay = chess.Board()
            self.san_stack = []
            for move in self.move_stack:
                self.san_stack.append(replay.san(move))
                replay.push(move)
            self.game_over = False
            self.result_text = ""
            self.clock_history = [(self.initial_time, self.initial_time)] * len(self.move_stack)
            self.redo_stack.clear()
            self.board_widget.set_board(self.board)
            self.board_widget.set_last_move(self.move_stack[-1] if self.move_stack else None)
            self._check_game_over()
            self._clear_premove()
            self._update_all()
            self._save_last_game()
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_last_game()
        self.clock_timer.stop()
        self.ai_worker.cancelled = True
        self.ai_worker.hint_cancelled = True
        self.ai_thread.quit()
        self.ai_thread.wait(4000)
        event.accept()
