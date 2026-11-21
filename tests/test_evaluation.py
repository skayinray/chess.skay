"""Basic sanity checks for the engine evaluation."""

from __future__ import annotations

import chess

from engine import MATE, evaluate

MATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def test_start_position_is_balanced() -> None:
    score = evaluate(chess.Board())
    assert abs(score) < 100


def test_material_advantage_changes_sign_with_side_to_move() -> None:
    board = chess.Board()
    for uci in ("e2e4", "d7d5", "e4d5"):
        board.push_uci(uci)

    assert board.turn == chess.BLACK
    assert evaluate(board) < 0
    board.turn = chess.WHITE
    assert evaluate(board) > 0


def test_checkmate_and_stalemate_scores() -> None:
    assert evaluate(chess.Board(MATE_FEN)) == -MATE
    assert evaluate(chess.Board(STALEMATE_FEN)) == 0


def test_extra_queen_is_worth_roughly_nine_pawns() -> None:
    board = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    score = evaluate(board)
    assert 700 < score < 1100
