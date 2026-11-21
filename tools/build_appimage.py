"""Build a slim chess.skay AppImage from the current Python environment.

Usage:
    python3 tools/build_appimage.py [path/to/appimagetool.AppImage]

Only the PySide6 modules, Qt libraries, plugins and standard library files that
the application actually uses are copied. In particular, Qt WebEngine and the
other unused Qt bindings are never included.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
APPDIR = BUILD / "AppDir"
OUTPUT = ROOT / "chess.skay-x86_64.AppImage"

PY_VERSION = f"python{sys.version_info.major}.{sys.version_info.minor}"

# PySide6 extension modules imported by src/*.py. QtSvg is intentionally not
# included: the board uses PNG pieces, and no SVG asset is loaded at runtime.
PYSIDE_MODULES = ("QtCore", "QtGui", "QtWidgets")
PYSIDE_PYTHON_FILES = ("__init__.py", "_config.py", "_git_pyside_version.py")

# Native libraries reachable from those modules and from the plugins below.
QT_LIB_PREFIXES = ("libQt6", "libshiboken6", "libpyside6")

# Only plugins the application can load. PNG support is built into QtGui.
PLUGINS = {
    "platforms": ("libqxcb.so", "libqoffscreen.so", "libqminimal.so"),
    "imageformats": ("libqico.so", "libqgif.so", "libqjpeg.so"),
    "platforminputcontexts": ("libcomposeplatforminputcontextplugin.so",),
}

# Not needed at runtime and responsible for most of the stdlib size.
STDLIB_SKIP_DIRS = {
    "__pycache__",
    "site-packages",
    "test",
    "tests",
    "idlelib",
    "tkinter",
    "lib2to3",
    "ensurepip",
    "turtledemo",
    "pydoc_data",
    "venv",
    "distutils",
    "Tools",
}
STDLIB_SKIP_FILES = {"turtle.py"}


def python_paths() -> tuple[Path, Path]:
    paths = sysconfig.get_paths()
    stdlib = Path(paths["stdlib"])
    candidates = [Path(paths["purelib"]), Path(paths.get("platlib", paths["purelib"]))]
    site_packages = next(
        (path for path in candidates if (path / "PySide6").is_dir()), candidates[0]
    )
    if not (site_packages / "PySide6").is_dir():
        site_packages = stdlib / "site-packages"
    return stdlib, site_packages


PY_STDLIB, SITE_PACKAGES = python_paths()


def qt_plugins_dir() -> Path:
    candidates = [
        SITE_PACKAGES / "PySide6" / "Qt" / "plugins",
        Path("/usr/lib/qt6/plugins"),
        Path("/usr/lib/x86_64-linux-gnu/qt6/plugins"),
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def library_search_dirs() -> list[Path]:
    return [
        SITE_PACKAGES / "PySide6" / "Qt" / "lib",
        Path("/usr/lib"),
        Path("/usr/lib64"),
        Path("/usr/lib/x86_64-linux-gnu"),
    ]


def ldd_paths(target: Path) -> tuple[list[Path], set[str]]:
    """Return resolved dependencies and unresolved SONAMEs for an ELF file."""
    try:
        result = subprocess.run(
            ["ldd", str(target)], capture_output=True, text=True,
            errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], set()

    paths: list[Path] = []
    missing: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.strip().split()
        if not fields:
            continue
        name = fields[0]
        if "=>" in fields:
            index = fields.index("=>")
            if index + 1 >= len(fields) or fields[index + 1] == "not":
                if name.startswith(QT_LIB_PREFIXES):
                    missing.add(name)
                continue
            path = fields[index + 1]
        elif len(fields) >= 2 and fields[1].startswith("/"):
            path = fields[1]
        else:
            continue
        if path.startswith("/"):
            paths.append(Path(path))
    return paths, missing


def collect_qt_libs(seeds: list[Path]) -> dict[str, Path]:
    """Walk the dynamic dependency graph, keeping only Qt and binding libs."""
    queue: deque[Path] = deque(seeds)
    found: dict[str, Path] = {}
    visited: set[Path] = set()
    missing: set[str] = set()

    while queue:
        target = queue.popleft()
        try:
            real = target.resolve()
        except OSError:
            continue
        if real in visited or not real.is_file():
            continue
        visited.add(real)

        dependencies, unresolved = ldd_paths(real)
        missing.update(unresolved)
        for dependency in dependencies:
            name = dependency.name
            if not name.startswith(QT_LIB_PREFIXES) or name in found:
                continue
            try:
                found[name] = dependency.resolve()
            except OSError:
                continue
            queue.append(found[name])

    # ldd cannot resolve libraries when a wheel ships them without an RPATH.
    for name in sorted(missing - set(found)):
        for directory in library_search_dirs():
            candidate = directory / name
            if candidate.exists():
                found[name] = candidate
                break
    return dict(sorted(found.items()))


def copy_stdlib() -> None:
    destination = APPDIR / "usr/lib" / PY_VERSION
    destination.mkdir(parents=True, exist_ok=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}

    for entry in sorted(PY_STDLIB.iterdir()):
        if entry.name in STDLIB_SKIP_DIRS or entry.name in STDLIB_SKIP_FILES:
            continue
        if entry.name.startswith("config-"):
            continue
        target = destination / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, ignore=ignore, symlinks=True)
        elif entry.is_file():
            shutil.copy2(entry, target)


def copy_python_packages() -> list[Path]:
    """Copy minimal PySide6, shiboken6 and python-chess. Return ldd seeds."""
    destination = APPDIR / "usr/lib" / PY_VERSION / "site-packages"
    destination.mkdir(parents=True, exist_ok=True)
    pyside_src = SITE_PACKAGES / "PySide6"
    pyside_dst = destination / "PySide6"
    pyside_dst.mkdir(parents=True, exist_ok=True)

    for name in PYSIDE_PYTHON_FILES:
        source = pyside_src / name
        if source.is_file():
            shutil.copy2(source, pyside_dst / name)
    support = pyside_src / "support"
    if support.is_dir():
        shutil.copytree(support, pyside_dst / "support", ignore=shutil.ignore_patterns("__pycache__"))

    seeds: list[Path] = []
    for module in PYSIDE_MODULES:
        matches = sorted(pyside_src.glob(f"{module}.*.so"))
        if not matches:
            matches = sorted(pyside_src.glob(f"{module}.so"))
        if not matches:
            raise SystemExit(f"PySide6.{module} extension module not found in {pyside_src}")
        for extension in matches:
            shutil.copy2(extension, pyside_dst / extension.name)
            seeds.append(extension)

    for package in ("shiboken6", "chess"):
        source = SITE_PACKAGES / package
        if source.is_dir():
            shutil.copytree(
                source, destination / package, symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
    return seeds


def copy_plugins() -> list[Path]:
    """Copy selected Qt plugins and return them as additional ldd seeds."""
    source_root = qt_plugins_dir()
    seeds: list[Path] = []
    for category, names in PLUGINS.items():
        directory = source_root / category
        if not directory.is_dir():
            continue
        for name in names:
            plugin = directory / name
            if not plugin.is_file():
                continue
            target = APPDIR / "usr/lib/qt/plugins" / category
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plugin, target / name)
            seeds.append(plugin)
    return seeds


def copy_python_runtime() -> Path:
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
    return executable


def copy_app_resources() -> None:
    shutil.copytree(
        ROOT / "src", APPDIR / "usr/share/chessskay/src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )
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


def write_desktop_and_apprun(executable: Path) -> None:
    desktop = """[Desktop Entry]
Type=Application
Name=chess.skay
GenericName=Chess
Comment=Offline chess with a local engine, clocks and hints
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


def main() -> int:
    tool = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/tmp/opencode/appimagetool.AppImage")
    if not tool.exists():
        print(f"appimagetool not found: {tool}", file=sys.stderr)
        return 1

    if APPDIR.exists():
        shutil.rmtree(APPDIR)
    for directory in ("usr/bin", "usr/lib", "usr/share/chessskay/src"):
        (APPDIR / directory).mkdir(parents=True, exist_ok=True)

    print("[1/6] Python interpreter and trimmed standard library")
    executable = copy_python_runtime()
    copy_stdlib()

    print("[2/6] Minimal PySide6, shiboken6 and python-chess")
    seeds = copy_python_packages()

    print("[3/6] Qt libraries and plugins required by those modules")
    seeds.extend(copy_plugins())
    for name, library in collect_qt_libs(seeds).items():
        shutil.copy2(library, APPDIR / "usr/lib" / name)

    print("[4/6] Application and desktop integration")
    copy_app_resources()
    write_desktop_and_apprun(executable)

    print("[5/6] appimagetool")
    extracted = BUILD / "squashfs-root"
    if not (extracted / "AppRun").exists():
        BUILD.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(tool), "--appimage-extract"], cwd=BUILD, check=True,
            stdout=subprocess.DEVNULL,
        )
    tool_bin = extracted / "AppRun"
    tool_bin.chmod(0o755)

    print("[6/6] Packaging AppImage")
    if OUTPUT.exists():
        OUTPUT.unlink()
    subprocess.run([str(tool_bin), "--no-appstream", str(APPDIR), str(OUTPUT)], check=True)

    size = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"\nDone: {OUTPUT} ({size:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
