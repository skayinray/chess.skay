"""Шахматная доска: кастомный QWidget с отрисовкой через QPainter."""

from __future__ import annotations

import math
from pathlib import Path

import chess
from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPen, QPixmap,
    QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

THEMES = {
    "chesscom": ("#eeeed2", "#769656", "#baca44", "#ffffff", "#1f2630"),
    "wood": ("#f0d9b5", "#b58863", "#7d5a3c", "#ffffff", "#1f2630"),
    "slate": ("#e8eef5", "#8ba5bf", "#43607d", "#ffffff", "#1d2b3a"),
    "night": ("#3c424f", "#272c37", "#151922", "#eaf2ff", "#0b0e14"),
    "emerald": ("#e3f0e4", "#6a9f74", "#356045", "#ffffff", "#16241a"),
}

# Набор фигур chess.com (neo) — тот самый стиль, с прозрачным фоном.
# Классический набор cburnett остаётся как альтернатива.
_RESOURCES = Path(__file__).resolve().parent / "resources"
PIECE_DIRS = {
    "chesscom": _RESOURCES / "pieces_chesscom",
    "classic": _RESOURCES / "pieces",
}
PIECE_SET = "chesscom"
PIECE_CODE = {
    chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
    chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K",
}


# Фигуры декодируются с диска один раз и кэшируются в нужном размере.
# Раньше каждый кадр анимации открывал 32 PNG-файла и заново их масштабировал —
# отсюда и лагала доска, и «зернилось» изображение из-за меняющихся дробных
# координат ресайза.
_BASE_CACHE: dict[tuple[str, str], QPixmap] = {}
_SIZED_CACHE: dict[tuple[str, str, int, int], QPixmap] = {}
_SIZED_CACHE_LIMIT = 192


def _piece_code(color: chess.Color, piece_type: chess.PieceType) -> str:
    return f"{'w' if color == chess.WHITE else 'b'}{PIECE_CODE[piece_type]}"


def set_piece_set(name: str) -> None:
    global PIECE_SET
    if name in PIECE_DIRS and name != PIECE_SET:
        PIECE_SET = name
        _BASE_CACHE.clear()
        _SIZED_CACHE.clear()


def piece_pixmap(color: chess.Color, piece_type: chess.PieceType) -> QPixmap:
    """Исходная (не масштабированная) фигура, загруженная с диска один раз."""
    key = (PIECE_SET, _piece_code(color, piece_type))
    pixmap = _BASE_CACHE.get(key)
    if pixmap is None:
        pixmap = QPixmap(str(PIECE_DIRS[PIECE_SET] / f"{key[1]}.png"))
        _BASE_CACHE[key] = pixmap
    return pixmap


def sized_piece_pixmap(color: chess.Color, piece_type: chess.PieceType,
                       side: int, dpr: float = 1.0) -> QPixmap:
    """Фигура, один раз масштабированная ровно под размер клетки.

    Возвращаемый пиксмап имеет devicePixelRatio = dpr, поэтому рисовать его
    нужно в логических координатах нужного размера — тогда масштабирование
    не будет «дёргаться» между кадрами.
    """
    side = max(1, int(side))
    ratio = max(1, int(round(dpr * 100)))
    key = (PIECE_SET, _piece_code(color, piece_type), side, ratio)
    cached = _SIZED_CACHE.get(key)
    if cached is not None:
        return cached
    base = piece_pixmap(color, piece_type)
    if base.isNull():
        return base
    device_side = max(1, int(math.ceil(side * dpr)))
    scaled = base.scaled(
        device_side, device_side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(dpr)
    if len(_SIZED_CACHE) >= _SIZED_CACHE_LIMIT:
        _SIZED_CACHE.clear()
    _SIZED_CACHE[key] = scaled
    return scaled


def piece_file(code: str) -> str:
    """Имя файла фигуры по коду вида 'wK'/'bP' для текущего набора."""
    return str(PIECE_DIRS[PIECE_SET] / f"{code}.png")


class ChessBoard(QWidget):
    moveMade = Signal(object)       # chess.Move
    premoveMade = Signal(object)    # chess.Move — ход, пока ждём opponent
    premoveCancelled = Signal()
    squareSelected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.board = chess.Board()
        self.flipped = False
        self.theme = "night"
        self.selected: int | None = None
        self.legal_targets: set[int] = set()
        self.last_move: chess.Move | None = None
        self.hint_move: chess.Move | None = None
        self.check_square: int | None = None
        self.premove_color: chess.Color | None = None
        self.premove: chess.Move | None = None
        self._geom: QRect | None = None  # кэш геометрии доски
        self._press_square: int | None = None
        self._dragging = False
        self.promotion_chooser = None  # callable(color) -> piece_type | None
        self.interactive = True

        # Mouse tracking выключен: hover нигде не рисуется, а заставлял
        # перерисовывать все 32 фигуры при каждом движении курсора.
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self._glow = QVariantAnimation(self)
        self._glow.setStartValue(0.0)
        self._glow.setEndValue(1.0)
        self._glow.setDuration(650)
        self._glow.valueChanged.connect(lambda _: self.update())

        # Плавное перемещение фигуры: список (figure, from, to) и прогресс.
        self._moving: list[tuple[chess.Piece, int, int]] = []
        self._captured: tuple[chess.Piece, int] | None = None
        self._move_anim = QVariantAnimation(self)
        self._move_anim.setStartValue(0.0)
        self._move_anim.setEndValue(1.0)
        self._move_anim.setDuration(320)
        self._move_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._move_anim.valueChanged.connect(lambda _: self.update())
        self._move_anim.finished.connect(self._finish_move_animation)

    # ------------------------------------------------------------- state ---

    def set_board(self, board: chess.Board) -> None:
        self._move_anim.stop()
        self._moving.clear()
        self._captured = None
        self.board = board
        self.clear_premove()
        self.check_square = None
        if board.is_check():
            king = board.king(board.turn)
            if king is not None:
                self.check_square = king
        self.clear_selection()
        self.update()

    def clear_selection(self) -> None:
        self.selected = None
        self.legal_targets.clear()
        self.squareSelected.emit(-1)

    def set_last_move(self, move: chess.Move | None, animate: bool = False) -> None:
        self.last_move = move
        if animate and move is not None:
            self._glow.stop()
            self._glow.start()
        self.update()

    def prepare_animation(self, board_before: chess.Board, move: chess.Move) -> None:
        """Вызвать до хода: запомнить фигуры, которые плавно переедут."""
        moving: list[tuple[chess.Piece, int, int]] = []
        mover = board_before.piece_at(move.from_square)
        if mover is not None:
            if move.promotion:
                mover = chess.Piece(move.promotion, mover.color)
            moving.append((mover, move.from_square, move.to_square))
        if board_before.is_castling(move):
            pairs = {
                chess.G1: (chess.H1, chess.F1), chess.C1: (chess.A1, chess.D1),
                chess.G8: (chess.H8, chess.F8), chess.C8: (chess.A8, chess.D8),
            }
            if move.to_square in pairs:
                rook_from, rook_to = pairs[move.to_square]
                rook = board_before.piece_at(rook_from)
                if rook is not None:
                    moving.append((rook, rook_from, rook_to))
        self._moving = moving

        capture_square = move.to_square
        if board_before.is_en_passant(move):
            capture_square = chess.square(chess.square_file(move.to_square),
                                          chess.square_rank(move.from_square))
        captured = board_before.piece_at(capture_square)
        self._captured = (captured, capture_square) if captured is not None else None
        self._move_anim.stop()
        self._move_anim.start()

    def _finish_move_animation(self) -> None:
        self._moving.clear()
        self._captured = None
        self.update()

    def set_hint(self, move: chess.Move | None) -> None:
        self.hint_move = move
        self.update()

    def set_premove_mode(self, color: chess.Color | None) -> None:
        """Разрешить выбирать фигуры цвета *color*, даже если сейчас не его ход."""
        if self.premove_color == color:
            return
        self.premove_color = color
        self.clear_selection()
        self.update()

    def set_premove(self, move: chess.Move | None) -> None:
        self.premove = move
        self.update()

    def clear_premove(self) -> None:
        if self.premove is not None:
            self.premove = None
            self.premoveCancelled.emit()
            self.update()

    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self.update()

    def set_theme(self, theme: str) -> None:
        if theme in THEMES:
            self.theme = theme
            self.update()

    def sizeHint(self):  # noqa: N802
        # MainWindow подгоняет ширину под высоту через _sync_board_width.
        return QSize(560, 560)

    # ----------------------------------------------------------- geometry ---

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._geom = None
        super().resizeEvent(event)

    def _board_rect(self) -> QRect:
        if self._geom is None:
            # Место под координаты: 20 слева и снизу, по 8 сверху/справа.
            size = min(self.width() - 28, self.height() - 28)
            # Кратно 8: тогда каждая клетка имеет целочисленные координаты —
            # не будет полупрозрачных швов и «дыхания» фигур между кадрами.
            size = max((size // 8) * 8, 8)
            left = 20 + max(0, (self.width() - 28 - size) // 2)
            top = 8 + max(0, (self.height() - 28 - size) // 2)
            self._geom = QRect(left, top, size, size)
        return self._geom

    def _square_rect(self, square: chess.Square) -> QRectF:
        rect = self._board_rect()
        cell = rect.width() / 8.0
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        col = 7 - file if self.flipped else file
        row = rank if self.flipped else 7 - rank
        return QRectF(rect.x() + col * cell, rect.y() + row * cell, cell, cell)

    def square_at(self, pos: QPoint) -> int | None:
        rect = self._board_rect()
        if not rect.contains(pos):
            return None
        cell = rect.width() / 8.0
        col = int((pos.x() - rect.x()) / cell)
        row = int((pos.y() - rect.y()) / cell)
        col = min(7, max(0, col))
        row = min(7, max(0, row))
        file = 7 - col if self.flipped else col
        rank = row if self.flipped else 7 - row
        return chess.square(file, rank)

    # ------------------------------------------------------------ painting --

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # Фигуры уже масштабированы заранее с SmoothTransformation, поэтому
        # здесь достаточно обычного преобразования — так они не «мылятся».
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        self._draw_background(painter)
        rect = self._board_rect()
        cell = rect.width() / 8.0
        light, dark, accent, fg, _bg = THEMES[self.theme]
        light_color, dark_color = QColor(light), QColor(dark)

        # a1 — тёмная: у белых поле h1 светлое. Формула ниже стандартная.
        for rank in range(8):
            for file in range(8):
                square = chess.square(file, rank)
                is_light = (file + rank) % 2 == 1
                sr = self._square_rect(square)
                painter.fillRect(sr, light_color if is_light else dark_color)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_check(painter)
        self._draw_last_move(painter, accent)
        self._draw_selection(painter)
        self._draw_premove(painter)
        self._draw_hint(painter)
        self._draw_targets(painter, cell)
        self._draw_pieces(painter, cell)
        self._draw_coordinates(painter, rect, cell, fg)
        painter.end()

    def _draw_background(self, painter: QPainter) -> None:
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor("#141922"))
        grad.setColorAt(1, QColor("#0c1017"))
        painter.fillRect(self.rect(), grad)

        rect = self._board_rect()
        painter.setPen(QPen(QColor("#3a4657"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(-1, -1, 1, 1))

    def _draw_check(self, painter: QPainter) -> None:
        if self.check_square is None:
            return
        sr = self._square_rect(self.check_square)
        grad = QRadialGradient(sr.center(), sr.width() * 0.62)
        grad.setColorAt(0, QColor(230, 55, 55, 190))
        grad.setColorAt(1, QColor(230, 55, 55, 0))
        painter.fillRect(sr, grad)

    def _draw_last_move(self, painter: QPainter, accent: str) -> None:
        move = self.last_move
        if move is None:
            return
        if self._glow.state() == QVariantAnimation.State.Running:
            pulse = 0.25 + 0.45 * float(self._glow.currentValue())
        else:
            pulse = 0.35
        color = QColor(accent)
        color.setAlphaF(pulse)
        for square in (move.from_square, move.to_square):
            painter.fillRect(self._square_rect(square), color)

    def _draw_selection(self, painter: QPainter) -> None:
        if self.selected is None:
            return
        color = QColor("#66c0f4")
        color.setAlphaF(0.55)
        painter.fillRect(self._square_rect(self.selected), color)
        pen = QPen(QColor("#9de0ff"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._square_rect(self.selected).adjusted(1, 1, -1, -1))

    def _draw_premove(self, painter: QPainter) -> None:
        """Оранжевые рамки и пунктирная стрелка запланированного хода."""
        move = self.premove
        if move is None:
            return
        accent = QColor("#ffa94d")
        for square in (move.from_square, move.to_square):
            sr = self._square_rect(square)
            painter.setPen(QPen(accent, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sr.adjusted(2, 2, -2, -2))
        painter.setPen(QPen(accent, 3, Qt.PenStyle.DashLine))
        painter.drawLine(self._square_rect(move.from_square).center(),
                         self._square_rect(move.to_square).center())

    def _draw_targets(self, painter: QPainter, cell: float) -> None:
        for square in self.legal_targets:
            sr = self._square_rect(square)
            capture = False
            if self.selected is not None:
                capture = self.board.piece_at(square) is not None or self.board.is_en_passant(
                    chess.Move(self.selected, square)
                )
            if capture:
                pen = QPen(QColor("#ff9d4d"), max(2.0, cell * 0.06))
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r = cell * 0.38
                painter.drawEllipse(sr.center(), r, r)
            else:
                radius = max(3.0, cell * 0.10)
                painter.setBrush(QBrush(QColor(90, 200, 255, 190)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(sr.center(), radius, radius)

    def _draw_hint(self, painter: QPainter) -> None:
        move = self.hint_move
        if move is None:
            return
        start = self._square_rect(move.from_square).center()
        end = self._square_rect(move.to_square).center()
        pen = QPen(QColor(120, 255, 160, 230), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(start, end)
        # arrowhead
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        head = 13
        p1 = QPointF(end.x() - head * math.cos(angle - 0.5), end.y() - head * math.sin(angle - 0.5))
        p2 = QPointF(end.x() - head * math.cos(angle + 0.5), end.y() - head * math.sin(angle + 0.5))
        painter.setBrush(QBrush(QColor(120, 255, 160, 230)))
        painter.drawPolygon(QPolygonF([end, p1, p2]))

    def _paint_piece(self, painter: QPainter, piece: chess.Piece,
                     center: QPointF, side: float) -> None:
        """Чистая фигура без теней и подложек, заранее масштабированная под клетку."""
        side_i = max(1, int(round(side)))
        pixmap = sized_piece_pixmap(piece.color, piece.piece_type, side_i,
                                    self.devicePixelRatioF())
        if pixmap.isNull():
            return
        x = round(center.x() - side_i / 2)
        y = round(center.y() - side_i / 2)
        painter.setOpacity(1.0)
        painter.drawPixmap(QRectF(x, y, side_i, side_i), pixmap, QRectF(pixmap.rect()))

    def _draw_pieces(self, painter: QPainter, cell: float) -> None:
        side = cell * 0.98
        animating = (self._move_anim.state() == QVariantAnimation.State.Running
                     and bool(self._moving))
        progress = float(self._move_anim.currentValue()) if animating else 1.0
        skip = {to for _, _, to in self._moving} if animating else set()

        for square, piece in self.board.piece_map().items():
            if square in skip:
                continue
            self._paint_piece(painter, piece, self._square_rect(square).center(), side)

        if not animating:
            return
        if self._captured is not None:
            captured, square = self._captured
            painter.setOpacity(max(0.0, 1.0 - progress))
            self._paint_piece(painter, captured, self._square_rect(square).center(), side)
            painter.setOpacity(1.0)
        for piece, from_square, to_square in self._moving:
            start = self._square_rect(from_square).center()
            end = self._square_rect(to_square).center()
            pos = QPointF(start.x() + (end.x() - start.x()) * progress,
                          start.y() + (end.y() - start.y()) * progress)
            # Очень лёгкая дуга — без «прыжка», как на chess.com.
            lift = math.sin(progress * math.pi) * cell * 0.06
            pos.setY(pos.y() - lift)
            fly_side = side
            self._paint_piece(painter, piece, pos, fly_side)

    def _draw_coordinates(self, painter: QPainter, rect: QRect, cell: float, fg: str) -> None:
        font = QFont()
        font.setPixelSize(max(9, int(cell * 0.24)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        files = "abcdefgh"
        for i in range(8):
            col = i if not self.flipped else 7 - i
            x = rect.x() + col * cell + cell / 2
            painter.drawText(QRectF(x - cell / 2, rect.bottom() + 1, cell, 18),
                             Qt.AlignmentFlag.AlignCenter, files[i])
            row = i if self.flipped else 7 - i
            y = rect.y() + row * cell + cell / 2
            painter.drawText(QRectF(rect.x() - 20, y - cell / 2, 18, cell),
                             Qt.AlignmentFlag.AlignCenter, str(i + 1))

    # -------------------------------------------------------------- input --

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.interactive:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.clear_premove()
            self.clear_selection()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        square = self.square_at(event.position().toPoint())
        self._press_square = square
        self._dragging = False
        if square is None:
            self.clear_selection()
            return
        # Клик по доступной клетке — это ход, а не снятие выделения.
        # Нажатие сохраняем, а ход выполняем в mouseReleaseEvent.
        if self.selected is not None and square in self.legal_targets:
            return
        active_color = (self.premove_color if self.premove_color is not None
                        else self.board.turn)
        piece = self.board.piece_at(square)
        if piece is not None and piece.color == active_color:
            self.selected = square
            if self.premove_color is not None:
                # Доска ещё не сделала ход соперника — считаем ходы от лица
                # ожидающей стороны, сохраняя текущее расположение фигур.
                probe = self.board.copy(stack=False)
                probe.turn = self.premove_color
                moves = probe.legal_moves
            else:
                moves = self.board.legal_moves
            self.legal_targets = {
                m.to_square for m in moves if m.from_square == square
            }
            self.squareSelected.emit(square)
        else:
            self.clear_selection()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        square = self.square_at(event.position().toPoint())
        if self._press_square is not None and square != self._press_square:
            self._dragging = True

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        release = self.square_at(event.position().toPoint())
        if (self.selected is not None and release is not None
                and release != self.selected and release in self.legal_targets):
            self._attempt(self.selected, release)
        self._press_square = None
        self._dragging = False

    def _attempt(self, from_sq: int, to_sq: int) -> None:
        if self.premove_color is not None:
            probe = self.board.copy(stack=False)
            probe.turn = self.premove_color
            moves_board = probe
        else:
            moves_board = self.board
        moves = [m for m in moves_board.legal_moves
                 if m.from_square == from_sq and m.to_square == to_sq]
        if not moves:
            self.clear_selection()
            self.update()
            return
        move = moves[0]
        if len(moves) > 1:  # превращение
            if self.promotion_chooser is None:
                return
            chosen = self.promotion_chooser(
                self.premove_color if self.premove_color is not None else self.board.turn
            )
            if chosen is None:
                self.clear_selection()
                self.update()
                return
            move = next((m for m in moves if m.promotion == chosen), moves[0])
        self.clear_selection()
        if self.premove_color is not None:
            self.set_premove(move)
            self.premoveMade.emit(move)
        else:
            self.moveMade.emit(move)
