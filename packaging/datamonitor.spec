# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Data Monitor (Windows .exe and macOS .app).

Do not run this file directly; use the scripts at the repository root,
which set up the platform toolchain first:

  build-windows.bat   MSYS2 mingw-w64 Python  ->  dist\\DataMonitor\\DataMonitor.exe
                      (+ DataMonitor-Setup-<version>.exe when Inno Setup 6 is found)
  build-mac.sh        Homebrew Python         ->  dist/Data Monitor.app + .dmg

GTK is loaded through GObject introspection at runtime, so the typelibs,
GLib schemas, gdk-pixbuf loaders and icon themes have to travel in the
bundle; ``runtime-hook.py`` then points the environment at them.
"""

import glob
import os
import re
import subprocess
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

with open(os.path.join(ROOT, "datamonitor", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
if not (IS_MAC or IS_WIN):
    raise SystemExit(
        "This spec builds the Windows .exe or the macOS .app. "
        "On Linux install normally with ./install.sh."
    )

ICON = os.path.join(
    SPECPATH, "datamonitor.icns" if IS_MAC else "datamonitor.ico"
)
if not os.path.exists(ICON):
    ICON = None

datas = [
    # Our own icon into the bundled hicolor theme (About dialog + .desktop).
    (
        os.path.join(SPECPATH, "datamonitor.svg"),
        "share/icons/hicolor/scalable/apps",
    ),
]
binaries = []
hiddenimports = collect_submodules("datamonitor")


def _exists_add(target: str, dest: str) -> None:
    if os.path.exists(target):
        datas.append((target, dest))


if IS_WIN:
    # MSYS2 mingw-w64 environment: sys.prefix IS the mingw64 prefix.
    prefix = sys.prefix
    binaries += [(dll, ".") for dll in glob.glob(os.path.join(prefix, "bin", "*.dll"))]
    query = os.path.join(prefix, "bin", "gdk-pixbuf-query-loaders.exe")
    if os.path.exists(query):
        binaries.append((query, "."))
    _exists_add(os.path.join(prefix, "lib", "girepository-1.0"), "lib/girepository-1.0")
    _exists_add(
        os.path.join(prefix, "share", "glib-2.0", "schemas"),
        "share/glib-2.0/schemas",
    )
    _exists_add(
        os.path.join(prefix, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders"),
        "lib/gdk-pixbuf-2.0/2.10.0/loaders",
    )
    _exists_add(os.path.join(prefix, "lib", "gio", "modules"), "lib/gio/modules")
    _exists_add(os.path.join(prefix, "share", "icons", "Adwaita"), "share/icons/Adwaita")
    _exists_add(os.path.join(prefix, "share", "icons", "hicolor"), "share/icons/hicolor")

if IS_MAC:
    def _brew(formula: str) -> str:
        return subprocess.check_output(
            ["brew", "--prefix", formula], text=True
        ).strip()

    # Collect the libraries of the GTK stack; their own dependency chains
    # (harfbuzz, graphite, epoxy ...) are then followed automatically by
    # macholib because Homebrew dylibs reference each other absolutely.
    for formula in ("gtk4", "libadwaita", "glib", "gdk-pixbuf", "cairo", "pango"):
        prefix = _brew(formula)
        binaries += [
            (dylib, "lib") for dylib in glob.glob(os.path.join(prefix, "lib", "*.dylib"))
        ]
        _exists_add(os.path.join(prefix, "lib", "girepository-1.0"), "lib/girepository-1.0")
        _exists_add(
            os.path.join(prefix, "share", "glib-2.0", "schemas"),
            "share/glib-2.0/schemas",
        )
        _exists_add(
            os.path.join(prefix, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders"),
            "lib/gdk-pixbuf-2.0/2.10.0/loaders",
        )
        _exists_add(os.path.join(prefix, "lib", "gio", "modules"), "lib/gio/modules")
        _exists_add(os.path.join(prefix, "share", "icons"), "share/icons")
    query = os.path.join(_brew("gdk-pixbuf"), "bin", "gdk-pixbuf-query-loaders")
    if os.path.exists(query):
        binaries.append((query, "."))

analysis = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    runtime_hooks=[os.path.join(SPECPATH, "runtime-hook.py")],
    hookspath=[],
    excludes=["tkinter"],
    noarchive=False,
)

exe = EXE(
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DataMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="DataMonitor",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Data Monitor.app",
        icon=ICON,
        bundle_identifier="io.datamonitor.App",
        version=VERSION,
        info_plist={
            "CFBundleName": "Data Monitor",
            "CFBundleDisplayName": "Data Monitor",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "© 2026 Patrick",
        },
    )
