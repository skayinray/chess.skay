"""Move generation used by the engine must be legal and complete."""

from __future__ import annotations

import chess
import pytest

from engine import _move_order

START_FEN = chess.STARTING_FEN
KIWIPETE_FEN = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


@pytest.mark.parametrize(
    ("fen", "expected"),
    [(START_FEN, 20), (KIWIPETE_FEN, 48)],
)
def test_legal_move_counts(fen: str, expected: int) -> None:
    board = chess.Board(fen)
    assert board.legal_moves.count() == expected


@pytest.mark.parametrize("fen", [START_FEN, KIWIPETE_FEN])
def test_move_order_contains_only_legal_moves(fen: str) -> None:
    board = chess.Board(fen)
    legal = set(board.legal_moves)
    ordered = _move_order(board, None)

    assert len(ordered) == len(legal)
    assert set(ordered) == legal
    assert all(board.is_legal(move) for move in ordered)


def test_move_order_prefers_transposition_move() -> None:
    board = chess.Board(START_FEN)
    first = _move_order(board, None)[0]
    assert _move_order(board, first)[0] == first


def test_captures_are_considered_legal_after_push() -> None:
    board = chess.Board()
    for uci in ("e2e4", "d7d5", "e4d5"):
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move)
    assert board.is_legal(chess.Move.from_uci("d8d5"))
