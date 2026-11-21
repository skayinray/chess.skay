"""PGN export and move history helpers used by the game window."""

from __future__ import annotations

import io

import chess
import chess.pgn
import pytest

MOVES = ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6")


def san_history(moves: list[chess.Move]) -> list[str]:
    """Rebuild the SAN move list the same way load_pgn does."""
    replay = chess.Board()
    history = []
    for move in moves:
        history.append(replay.san(move))
        replay.push(move)
    return history


@pytest.fixture
def played_board() -> chess.Board:
    board = chess.Board()
    for uci in MOVES:
        board.push_uci(uci)
    return board


def test_san_history(played_board: chess.Board) -> None:
    history = san_history(list(played_board.move_stack))
    assert history == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


def test_pgn_round_trip(played_board: chess.Board) -> None:
    game = chess.pgn.Game.from_board(played_board)
    game.headers["White"] = "chess.skay"
    game.headers["Result"] = played_board.result()
    text = str(game)

    loaded = chess.pgn.read_game(io.StringIO(text))
    assert loaded is not None
    board = chess.Board()
    for move in loaded.mainline_moves():
        board.push(move)

    assert list(board.move_stack) == list(played_board.move_stack)
    assert board.fen() == played_board.fen()
    assert san_history(list(board.move_stack)) == san_history(list(played_board.move_stack))


def test_restore_game_from_san(played_board: chess.Board) -> None:
    """Saved games keep SAN, which must replay to the same move stack."""
    saved_san = san_history(list(played_board.move_stack))
    restored = chess.Board()
    moves = []
    for san in saved_san:
        move = restored.parse_san(san)
        moves.append(move)
        restored.push(move)

    assert moves == list(played_board.move_stack)
    assert restored.fen() == played_board.fen()
