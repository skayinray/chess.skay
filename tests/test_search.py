"""Search must return legal moves and honour its deadline."""

from __future__ import annotations

import time

import chess

from engine import Engine, choose_move

OPEN_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"


def test_search_returns_legal_move() -> None:
    board = chess.Board(OPEN_FEN)
    result = Engine().search(board, max_depth=2, time_limit=2.0)

    assert result.move in board.legal_moves
    assert result.depth >= 1
    assert result.nodes > 0
    assert board.move_stack == []


def test_choose_move_returns_legal_move_for_each_level() -> None:
    board = chess.Board()
    for level in ("easy", "medium"):
        result = choose_move(board, level)
        assert result is not None
        assert result.move in board.legal_moves


def test_search_with_deadline_stops_promptly() -> None:
    board = chess.Board(OPEN_FEN)
    started = time.monotonic()
    result = Engine().search_with_deadline(board, max_depth=20, time_limit=0.05)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert result.elapsed < 2.0
    assert result.move in board.legal_moves


def test_cancel_callback_stops_search() -> None:
    board = chess.Board(OPEN_FEN)
    engine = Engine()
    engine.cancel_cb = lambda: True
    started = time.monotonic()
    result = engine.search_with_deadline(board, max_depth=20, time_limit=5.0)

    assert time.monotonic() - started < 2.0
    assert result.move is None or result.move in board.legal_moves


def test_search_on_terminal_position_returns_no_move() -> None:
    board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    result = Engine().search(board, max_depth=2, time_limit=1.0)
    assert result.move is None
