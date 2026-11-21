# chess.skay

An offline desktop chess client for Linux and Windows, with its own Python chess engine. No external engine, account, or network connection is needed to play.

Author: skayinray <https://github.com/skayinray>. Licensed under MIT, see [LICENSE](LICENSE).

## Features

- Chess rules: castling, en passant, promotion, checkmate, stalemate, insufficient material, 50/75 move rules, and threefold repetition.
- Local engine: alpha-beta search with iterative deepening, a transposition table, and material plus piece square table evaluation. Four levels: easy, club, master, and expert.
- Play against the computer or another person, resume a saved game, and use hints during play.
- Move entry by click or drag, premoves while the computer is thinking, board flip, last move and check highlighting, captured pieces, and an evaluation bar.
- Five board themes and two piece sets. Cyrillic fonts are bundled with the AppImage so text does not depend on system fonts.
- Clocks with increment, SAN move list, undo/redo, resignation, automatic save of the last game, and PGN import/export.
- Elo rating stored between sessions (K=32).

The AppImage shows arrows for hints and planned premoves, and animates piece movement. The engine runs in a worker thread.

## Running

Download a build from [Releases](https://github.com/skayinray/chess.skay/releases).

Linux:

```bash
chmod +x chess.skay-x86_64.AppImage
./chess.skay-x86_64.AppImage
```

Windows 10/11 (x86_64): download `chess.skay-windows-x86_64.exe` and run it. No installation is required.

The AppImage bundles Python, PySide6, Qt, python-chess, fonts, and piece images. The Windows build is a single PyInstaller executable.

## Verifying a release

Each release publishes `SHA256SUMS-linux` and `SHA256SUMS-windows` (with matching `.sig` files), plus a `.sig` file for every asset. Signatures are Ed25519 over the file bytes and are base64 encoded. The public key is:

```
CtH8fQqA3o/mFsZ2fRRrUzmijmvKL6OMCaDqY4tt37c=
```

Verify with the included tool (requires `cryptography`):

```bash
python3 -m pip install -r requirements.txt
python3 tools/sign_release.py verify chess.skay-x86_64.AppImage chess.skay-x86_64.AppImage.sig
python3 tools/sign_release.py verify SHA256SUMS-linux SHA256SUMS-linux.sig
sha256sum -c SHA256SUMS-linux
```

## Building

Linux AppImage:

```bash
python3 -m pip install -r requirements.txt
./build_appimage.sh /path/to/appimagetool.AppImage
```

The build copies only the PySide6 modules, Qt libraries, plugins, and standard library files that the app needs. The resulting AppImage is well under 60 MiB. `build/` and generated AppImages are gitignored.

Windows: the `Build Windows exe` workflow builds a onefile executable with PyInstaller and uploads it to the release.

macOS: no CI job is configured. To build manually, install the requirements and run:

```bash
python3 -m pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name chess.skay \
  --add-data "src/resources:resources" src/main.py
```

macOS builds are not signed or notarized.

## Tests

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q
```

Tests are offline, use only the engine and python-chess, and do not start the GUI.

## Layout

```
src/
  main.py              entry point
  chess_app.py         main window, game logic, clocks, AI thread
  board_widget.py      board rendering and input
  engine.py            search and evaluation
  dialogs.py           new game, promotion, and about dialogs
  resources/           icon, fonts, piece images, AppStream metadata
tools/
  build_appimage.py    slim AppImage builder
  sign_release.py      release signing and verification
  make_icon.py         icon generator
tests/                 pytest suite for the engine and helpers
.github/workflows/
  ci.yml               tests and signed Linux release assets
  build-windows.yml    signed Windows release asset
```
