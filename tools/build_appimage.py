"""Сборка chess.skay-x86_64.AppImage из локального окружения.

Использование:
    python3 tools/build_appimage.py [путь/к/appimagetool.AppImage]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
APPDIR = BUILD / "AppDir"
OUTPUT = ROOT / "chess.skay-x86_64.AppImage"

PY_VERSION = f"python{sys.version_info.major}.{sys.version_info.minor}"
PY_STDLIB = Path(sys.base_prefix) / "lib" / PY_VERSION
SITE_PACKAGES = PY_STDLIB / "site-packages"


def qt_plugins_dir() -> Path:
    system = Path("/usr/lib/qt6/plugins")
    if system.exists():
        return system
    return SITE_PACKAGES / "PySide6" / "Qt" / "plugins"


QT_PLUGIN_DIRS = (
    "platforms", "imageformats", "iconengines", "platformthemes",
    "styles", "egldeviceintegrations", "generic", "tls",
)


def ignored_stdlib(directory: str, names: list[str]) -> set[str]:
    skip = {
        "site-packages", "__pycache__", "test", "idlelib", "tkinter",
        "lib2to3", "ensurepip", "turtledemo", "distutils", "ensurepip",
    }
    return {name for name in names if name in skip}


def collect_qt_libs() -> list[Path]:
    targets: list[Path] = []
    pyside_dir = SITE_PACKAGES / "PySide6"
    if pyside_dir.exists():
        targets.extend(sorted(pyside_dir.glob("Qt*.so")))
    for name in QT_PLUGIN_DIRS:
        directory = qt_plugins_dir() / name
        if directory.exists():
            targets.extend(sorted(directory.glob("*.so")))

    found: dict[str, Path] = {}
    for target in targets:
        try:
            result = subprocess.run(
                ["ldd", str(target)], capture_output=True, text=True, timeout=20, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in result.stdout.splitlines():
            path = line.split("=>")[-1].strip().split(" ")[0] if "=>" in line else line.strip().split(" ")[0]
            if not path.startswith("/"):
                continue
            candidate = Path(path)
            if candidate.name.startswith(("libQt6", "libshiboken6")):
                found[candidate.name] = candidate
    return [found[name] for name in sorted(found)]


def main() -> int:
    tool = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/tmp/opencode/appimagetool.AppImage")
    if not tool.exists():
        print(f"appimagetool не найден: {tool}", file=sys.stderr)
        return 1

    if APPDIR.exists():
        shutil.rmtree(APPDIR)
    (APPDIR / "usr/bin").mkdir(parents=True)
    (APPDIR / "usr/lib").mkdir(parents=True)
    (APPDIR / "usr/share/chessskay/src").mkdir(parents=True)

    print("[1/6] Python interpreter + stdlib")
    executable = Path(sys.executable).resolve()
    shutil.copy2(executable, APPDIR / "usr/bin" / executable.name)
    (APPDIR / "usr/bin/python3").symlink_to(executable.name)
    libdir = Path(sysconfig.get_config_var("LIBDIR") or "")
    for name in {
        sysconfig.get_config_var("INSTSONAME"),
        sysconfig.get_config_var("LDLIBRARY"),
    } - {None}:
        candidate = libdir / str(name)
        if candidate.exists():
            shutil.copy2(candidate.resolve(), APPDIR / "usr/lib" / candidate.name)
    shutil.copytree(
        PY_STDLIB, APPDIR / "usr/lib" / PY_VERSION,
        ignore=ignored_stdlib, symlinks=True,
    )

    print("[2/6] PySide6 + shiboken6 + python-chess")
    site_dst = APPDIR / "usr/lib" / PY_VERSION / "site-packages"
    site_dst.mkdir(parents=True, exist_ok=True)
    for package in ("PySide6", "shiboken6", "chess"):
        source = SITE_PACKAGES / package
        if source.exists():
            shutil.copytree(source, site_dst / package, symlinks=True)

    print("[3/6] Qt libraries")
    for library in collect_qt_libs():
        shutil.copy2(library.resolve(), APPDIR / "usr/lib" / library.name)
    for name in QT_PLUGIN_DIRS:
        directory = qt_plugins_dir() / name
        if directory.exists():
            shutil.copytree(
                directory, APPDIR / "usr/lib/qt/plugins" / name,
                symlinks=True, dirs_exist_ok=True,
            )

    print("[4/6] Приложение + иконка")
    shutil.copytree(
        ROOT / "src", APPDIR / "usr/share/chessskay/src",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
    # Шрифты с кириллицей — чтобы текст не зависел от системного fontconfig.
    resources_dst = APPDIR / "usr/share/chessskay/src/resources"
    for name in (
        "NotoSans-Regular.ttf", "NotoSans-Bold.ttf",
        "NotoSansMono-Regular.ttf", "NotoSansMono-Bold.ttf",
    ):
        source = Path("/usr/share/fonts/noto") / name
        if source.exists():
            shutil.copy2(source, resources_dst / name)

    icon = ROOT / "src/resources/icon.png"
    icon_dst = APPDIR / "usr/share/icons/hicolor/256x256/apps/chessskay.png"
    icon_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon, icon_dst)
    shutil.copy2(icon, APPDIR / "chessskay.png")
    (APPDIR / ".DirIcon").symlink_to("chessskay.png")
    metainfo = ROOT / "src/resources/chess.skay.appdata.xml"
    if metainfo.exists():
        target = APPDIR / "usr/share/metainfo/chess.skay.appdata.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(metainfo, target)

    desktop = """[Desktop Entry]
Type=Application
Name=chess.skay
GenericName=Chess
Comment=Шахматы с собственным движком, часами и подсказками
Exec=chess.skay
Icon=chessskay
Terminal=false
Categories=Game;BoardGame;
StartupNotify=true
"""
    (APPDIR / "chess.skay.desktop").write_text(desktop, encoding="utf-8")
    applications = APPDIR / "usr/share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    (applications / "chess.skay.desktop").write_text(desktop, encoding="utf-8")

    apprun = f"""#!/bin/sh
APPDIR="$(dirname "$(readlink -f "$0")")"
export APPDIR
export LD_LIBRARY_PATH="$APPDIR/usr/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
export QT_PLUGIN_PATH="$APPDIR/usr/lib/qt/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$APPDIR/usr/lib/qt/plugins/platforms"
export PYTHONPATH="$APPDIR/usr/lib/{PY_VERSION}/site-packages"
export XDG_DATA_DIRS="$APPDIR/usr/share:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"
exec "$APPDIR/usr/bin/{executable.name}" "$APPDIR/usr/share/chessskay/src/main.py" "$@"
"""
    apprun_path = APPDIR / "AppRun"
    apprun_path.write_text(apprun, encoding="utf-8")
    apprun_path.chmod(0o755)

    print("[5/6] Подготовка appimagetool")
    extracted = BUILD / "squashfs-root"
    if not (extracted / "AppRun").exists():
        subprocess.run([str(tool), "--appimage-extract"], cwd=BUILD, check=True,
                       stdout=subprocess.DEVNULL)
    tool_bin = extracted / "AppRun"
    tool_bin.chmod(0o755)

    print("[6/6] Упаковка AppImage")
    if OUTPUT.exists():
        OUTPUT.unlink()
    subprocess.run([str(tool_bin), "--no-appstream", str(APPDIR), str(OUTPUT)], check=True)

    size = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"\nГотово: {OUTPUT} ({size:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
