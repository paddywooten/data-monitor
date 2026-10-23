# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller runtime hook: point the bundled GTK stack at its files.

Runs inside the frozen executable before any application code.  Without
this, GObject introspection would look for typelibs, GLib schemas and
gdk-pixbuf loaders in the build machine's prefix (MSYS2 / Homebrew) and
fail on any other computer.
"""

import glob
import os
import subprocess
import sys
import tempfile

if getattr(sys, "frozen", False):
    base = sys._MEIPASS

    # GObject introspection: the .typelib files collected into the bundle.
    typelib_dir = os.path.join(base, "lib", "girepository-1.0")
    if os.path.isdir(typelib_dir):
        os.environ["GI_TYPELIB_PATH"] = typelib_dir

    # GLib schemas (Adw/Gtk settings) + general themedata lookup.
    schemas = os.path.join(base, "share", "glib-2.0", "schemas")
    if os.path.isdir(schemas):
        os.environ["GSETTINGS_SCHEMA_DIR"] = schemas
    share = os.path.join(base, "share")
    if os.path.isdir(share):
        os.environ["XDG_DATA_DIRS"] = os.pathsep.join(
            [share, "/usr/local/share", "/usr/share"]
        )
    os.environ["GTK_DATA_PREFIX"] = base

    # GIO modules (proxy resolver etc.), when the platform ships any.
    gio_modules = os.path.join(base, "lib", "gio", "modules")
    if glob.glob(os.path.join(gio_modules, "*")):
        os.environ["GIO_MODULE_DIR"] = gio_modules

    # gdk-pixbuf loaders: the shipped loaders.cache (if any) contains the
    # build machine's absolute paths, so regenerate one for this bundle.
    suffix = ".dll" if os.name == "nt" else ".so"
    loaders = sorted(
        glob.glob(os.path.join(base, "lib", "gdk-pixbuf-2.0", "*", "loaders", "*" + suffix))
    )
    query = os.path.join(
        base, "gdk-pixbuf-query-loaders" + (".exe" if os.name == "nt" else "")
    )
    if loaders and os.path.isfile(query):
        try:
            output = subprocess.run(
                [query] + loaders, capture_output=True, text=True, timeout=30
            ).stdout
        except (OSError, subprocess.SubprocessError):
            output = ""
        if output.strip():
            cache = os.path.join(
                tempfile.gettempdir(), "datamonitor-loaders.cache"
            )
            try:
                with open(cache, "w", encoding="utf-8") as fh:
                    fh.write(output)
                os.environ["GDK_PIXBUF_MODULEDIR"] = os.path.dirname(loaders[0])
                os.environ["GDK_PIXBUF_MODULE_FILE"] = cache
            except OSError:
                pass
