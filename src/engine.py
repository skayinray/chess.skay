"""Шахматный движок: оценка позиции и поиск minimax с alpha-beta.

Использует python-chess только для генерации ходов и правил. Никаких
внешних движков (Stockfish и т.п.) не требуется — всё считается на Python,
поэтому приложение остаётся полностью автономным.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import chess
import chess.polyglot

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Таблицы записаны от 8-й горизонтали к 1-й (как на доске). Индекс ячейки
# доски python-chess переводится через `sq ^ 56`.
_PST_RAW: dict[chess.PieceType, list[int]] = {
    chess.PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    chess.KNIGHT: [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ],
    chess.BISHOP: [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ],
    chess.ROOK: [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, 10, 10, 10, 10, 5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        0, 0, 0, 5, 5, 0, 0, 0,
    ],
    chess.QUEEN: [
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20,
    ],
    chess.KING: [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20,
    ],
}

_KING_END = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50,
]

MATE = 100_000


def _table_score(table: list[int], square: chess.Square, color: chess.Color) -> int:
    idx = square ^ 56
    if color == chess.BLACK:
        idx = chess.square_mirror(square) ^ 56
    return table[idx]


def evaluate(board: chess.Board) -> int:
    """Оценка в центурионах с точки зрения стороны, которая сейчас ходит."""
    if board.is_checkmate():
        return -MATE
    if board.is_stalemate() or board.is_insufficient_material() or board.is_repetition(3):
        return 0

    score = 0
    heavy = 0
    for square, piece in board.piece_map().items():
        value = PIECE_VALUES[piece.piece_type]
        if piece.piece_type not in (chess.PAWN, chess.KING):
            heavy += value
        table = _KING_END if piece.piece_type == chess.KING and heavy < 1300 else _PST_RAW[piece.piece_type]
        total = value + _table_score(table, square, piece.color)
        score += total if piece.color == chess.WHITE else -total

    # Небольшой бонус за пару слонов.
    if len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2:
        score += 25
    if len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2:
        score -= 25

    return score if board.turn == chess.WHITE else -score


def _move_order(board: chess.Board, tt_move: chess.Move | None) -> list[chess.Move]:
    """Сначала хед из TT, потом взятия (MVV-LVA), потом остальные ходы."""
    moves = list(board.legal_moves)
    if tt_move and tt_move in moves:
        moves.remove(tt_move)
        moves.insert(0, tt_move)

    def key(move: chess.Move) -> int:
        score = 0
        if board.is_capture(move):
            victim = board.piece_type_at(move.to_square)
            victim_val = PIECE_VALUES[victim] if victim else 100  # en passant
            attacker = board.piece_type_at(move.from_square)
            score += 10_000 + victim_val * 10 - PIECE_VALUES[attacker]
        if move.promotion:
            score += 9_000 + PIECE_VALUES.get(move.promotion, 0)
        # gives_check() на каждом ходе каждого узла стоил очень дорого и
        # почти не влиял на качество порядка ходов — убираем.
        return score

    moves.sort(key=key, reverse=True)
    return moves


@dataclass
class SearchResult:
    move: chess.Move | None
    score: int
    depth: int
    nodes: int
    elapsed: float


class Engine:
    """Alpha-beta поиск с итеративным углублением и таблицей перестановок."""

    def __init__(self) -> None:
        self.tt: dict[int, tuple[int, int, int, chess.Move]] = {}
        self.nodes = 0
        self.stop = False
        self.cancel_cb = None

    def search(self, board: chess.Board, max_depth: int = 3,
               time_limit: float = 8.0) -> SearchResult:
        self.nodes = 0
        self.stop = False
        started = time.monotonic()
        best_move: chess.Move | None = None
        best_score = 0
        reached = 0
        root_moves = list(board.legal_moves)
        if not root_moves:
            return SearchResult(None, 0, 0, 0, 0.0)

        for depth in range(1, max_depth + 1):
            if time.monotonic() - started > time_limit:
                break
            score, move = self._root(board, depth, best_move)
            if move is not None:
                best_move, best_score, reached = move, score, depth
            if abs(score) > MATE - 1000:
                break
        return SearchResult(best_move, best_score, reached, self.nodes,
                            time.monotonic() - started)

    def _root(self, board: chess.Board, depth: int,
              previous: chess.Move | None) -> tuple[int, chess.Move | None]:
        alpha, beta = -MATE * 2, MATE * 2
        best_move = previous
        best_score = -MATE * 3
        ordered = _move_order(board, previous)
        for move in ordered:
            board.push(move)
            score = -self._alphabeta(board, depth - 1, -beta, -alpha)
            board.pop()
            if self.stop:
                break
            if score > best_score:
                best_score, best_move = score, move
            if score > alpha:
                alpha = score
        return best_score, best_move

    def _alphabeta(self, board: chess.Board, depth: int,
                   alpha: int, beta: int) -> int:
        self.nodes += 1
        if self.nodes % 256 == 0:
            if time.monotonic() > self._deadline or (self.cancel_cb and self.cancel_cb()):
                self.stop = True
                return evaluate(board)
            # Отдаём GIL, чтобы Qt успевал перерисовывать анимацию во время поиска.
            time.sleep(0)
        if board.is_checkmate():
            return -MATE + (50 - depth)
        if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_fifty_moves():
            return 0
        if depth <= 0:
            return evaluate(board)

        key = chess.polyglot.zobrist_hash(board)
        tt = self.tt.get(key)
        tt_move = tt[3] if tt else None
        if tt and tt[0] >= depth:
            _, flag, value, _ = tt
            if flag == 0:
                return value
            if flag == 1 and value >= beta:
                return value
            if flag == 2 and value <= alpha:
                return value

        alpha_orig = alpha
        best = -MATE * 2
        best_move = None
        for move in _move_order(board, tt_move):
            board.push(move)
            score = -self._alphabeta(board, depth - 1, -beta, -alpha)
            board.pop()
            if self.stop:
                break
            if score > best:
                best, best_move = score, move
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        if best_move is not None:
            flag = 0 if alpha_orig < best < beta else (1 if best >= beta else 2)
            self.tt[key] = (depth, flag, best, best_move)
        return best

    _deadline = 0.0

    def search_with_deadline(self, board: chess.Board, max_depth: int,
                             time_limit: float) -> SearchResult:
        self._deadline = time.monotonic() + time_limit
        return self.search(board, max_depth, time_limit)


DIFFICULTY = {
    "easy": (1, 0.4, "Случайный новичок"),
    "medium": (3, 2.5, "Клубный игрок"),
    "hard": (4, 6.0, "Мастер"),
    "expert": (5, 14.0, "Гроссмейстер"),
}


def choose_move(board: chess.Board, level: str = "medium",
                cancel_cb=None) -> SearchResult | None:
    """Удобная точка входа: вернуть ход заданной сложности."""
    depth, limit, _ = DIFFICULTY.get(level, DIFFICULTY["medium"])
    engine = Engine()
    engine.cancel_cb = cancel_cb
    result = engine.search_with_deadline(board.copy(stack=False), depth, limit)
    if result.move is None:
        return None
    if level == "easy":
        # Немного случайности, чтобы новичок не был идеальным.
        import random
        moves = list(board.legal_moves)
        if random.random() < 0.45 and len(moves) > 1:
            result.move = random.choice(moves)
    return result
