"""Stylesheet + colour palettes for the GTK4 UI."""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

CSS = """
/* ---- generic cards ---------------------------------------------------- */
.dw-card {
    background: alpha(currentColor, 0.035);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 14px;
    padding: 14px 16px 13px 16px;
}
.dw-card-title {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    color: alpha(currentColor, 0.55);
}
.dw-value {
    font-size: 26px;
    font-weight: 800;
    margin-top: 4px;
}
.dw-value.dw-small { font-size: 20px; }
.dw-card-sub {
    font-size: 12px;
    color: alpha(currentColor, 0.55);
    margin-top: 1px;
}
.dw-down   { color: @success_color; }
/* A literal blue: @accent_color follows the desktop accent (red on this
   machine), which would read as an error rather than "upload". */
.dw-up     { color: #478fe8; }
.dw-warn   { color: @warning_color; }
.dw-error  { color: @error_color; }
.dw-muted  { color: alpha(currentColor, 0.55); }

/* ---- quota panel ------------------------------------------------------ */
.dw-quota {
    background: alpha(currentColor, 0.035);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 14px;
    padding: 12px 16px 12px 16px;
}
.dw-heading { font-size: 13px; font-weight: 700; }
.dw-caption { font-size: 12px; color: alpha(currentColor, 0.60); }

progressbar { min-height: 10px; }
progressbar trough {
    background: alpha(currentColor, 0.10);
    border-radius: 999px;
    min-height: 10px;
}
progressbar progress {
    border-radius: 999px;
    min-height: 10px;
    background: @success_color;
}
progressbar.dw-progress-warn progress { background: @warning_color; }
progressbar.dw-progress-error progress { background: @error_color; }

/* ---- tables (history + interfaces) ----------------------------------- */
.dw-table { background: transparent; }
.dw-table row {
    border-bottom: 1px solid alpha(currentColor, 0.07);
    padding: 0;
}
.dw-table row:last-child { border-bottom: none; }
.dw-cell { font-size: 13px; padding: 9px 8px; }
.dw-cell-header {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    color: alpha(currentColor, 0.50);
    padding: 4px 8px;
}
.dw-cell-dim { color: alpha(currentColor, 0.60); }

/* ---- graph / charts --------------------------------------------------- */
.dw-graph {
    background: alpha(currentColor, 0.03);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 14px;
}
.dw-legend { font-size: 12px; color: alpha(currentColor, 0.60); }

/* ---- misc ------------------------------------------------------------- */
.dw-page { padding: 14px; }
.dw-section-title {
    font-size: 15px;
    font-weight: 700;
    margin-top: 6px;
}
.dw-note { font-size: 12px; color: alpha(currentColor, 0.55); }
dw-header-bar { background: transparent; }
"""

# Dark palette used by the cairo charts (GTK CSS colours cannot be queried
# at runtime, so the charts pick a palette that matches the active scheme).
_DARK = {
    "text": (0.90, 0.93, 0.96, 1.0),
    "dim": (0.55, 0.60, 0.66, 1.0),
    "grid": (1.0, 1.0, 1.0, 0.07),
    "down": (0.247, 0.725, 0.314, 1.0),  # #3fb950
    "up": (0.345, 0.651, 1.0, 1.0),      # #58a6ff
    "warn": (0.886, 0.702, 0.188, 1.0),
    "error": (1.0, 0.482, 0.447, 1.0),
    "hover": (1.0, 1.0, 1.0, 0.14),
}

_LIGHT = {
    "text": (0.10, 0.12, 0.15, 1.0),
    "dim": (0.42, 0.46, 0.52, 1.0),
    "grid": (0.0, 0.0, 0.0, 0.09),
    "down": (0.11, 0.55, 0.24, 1.0),
    "up": (0.10, 0.42, 0.85, 1.0),
    "warn": (0.71, 0.50, 0.05, 1.0),
    "error": (0.85, 0.20, 0.17, 1.0),
    "hover": (0.0, 0.0, 0.0, 0.08),
}


def is_dark() -> bool:
    try:
        manager = Adw.StyleManager.get_default()
        getter = getattr(manager, "is_dark", None) or getattr(manager, "get_dark")
        return bool(getter())
    except Exception:
        return True


def palette() -> dict:
    return _DARK if is_dark() else _LIGHT


def apply_color_scheme(scheme: str) -> None:
    manager = Adw.StyleManager.get_default()
    if scheme == "dark":
        manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    elif scheme == "light":
        manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    else:
        manager.set_color_scheme(Adw.ColorScheme.DEFAULT)


def install_css(display=None) -> None:
    display = display or Gdk_display()
    provider = Gtk.CssProvider()
    data = CSS.encode("utf-8")
    loader = getattr(provider, "load_from_string", None)
    if loader is not None:
        try:
            loader(CSS)
        except TypeError:
            loader(data)
    else:  # pragma: no cover - older GTK
        provider.load_from_data(data)
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def Gdk_display():
    from gi.repository import Gdk

    return Gdk.Display.get_default()


# ---------------------------------------------------------------------------
# KDE colour pickup
#
# libadwaita ignores GTK themes, so on Plasma the window would otherwise keep
# GNOME's stock palette. When running under KDE we read the active colour
# scheme from kdeglobals and map it onto libadwaita's named colours. The
# provider sits at APPLICATION priority, so a user's ~/.config/gtk-4.0/gtk.css
# (USER priority) still wins. Alpha channels are dropped: GTK cannot blur
# what is behind the window, so translucent "glass" schemes would just show
# the wallpaper through the UI.
# ---------------------------------------------------------------------------

_kde_provider = None
_kde_monitor = None
_kde_reload_id = 0


def _kdeglobals_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "kdeglobals")


def _running_kde() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "kde" in desktop.lower().split(":") or bool(
        os.environ.get("KDE_FULL_SESSION")
    )


def parse_kdeglobals(text: str) -> dict:
    """Parse kdeglobals into {section: {key: value}}.

    Section headers such as ``[Colors:Header][Inactive]`` are kept verbatim
    (minus the outer brackets) as ``Colors:Header][Inactive``.
    """
    sections: dict = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    return sections


def _kde_rgb(value):
    """'r,g,b[,a]' -> (r, g, b) ints, or None if unparseable."""
    if not value:
        return None
    parts = value.split(",")
    if len(parts) < 3:
        return None
    try:
        rgb = tuple(max(0, min(255, int(p.strip()))) for p in parts[:3])
    except ValueError:
        return None
    return rgb


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def _luminance(rgb) -> float:
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kde_colors(sections: dict) -> dict:
    """Map a parsed kdeglobals onto libadwaita named colours (hex strings).

    Returns an empty dict when the file lacks a usable window colour.
    """

    def get(section, key):
        return _kde_rgb(sections.get(section, {}).get(key))

    window_bg = get("Colors:Window", "BackgroundNormal")
    window_fg = get("Colors:Window", "ForegroundNormal")
    if window_bg is None or window_fg is None:
        return {}

    view_bg = get("Colors:View", "BackgroundNormal") or window_bg
    view_fg = get("Colors:View", "ForegroundNormal") or window_fg
    header_bg = (
        get("Colors:Header", "BackgroundNormal")
        or get("WM", "activeBackground")
        or window_bg
    )
    header_fg = (
        get("Colors:Header", "ForegroundNormal")
        or get("WM", "activeForeground")
        or window_fg
    )
    header_backdrop = (
        get("Colors:Header][Inactive", "BackgroundNormal")
        or get("WM", "inactiveBackground")
        or header_bg
    )
    alt_bg = get("Colors:Window", "BackgroundAlternate") or window_bg
    accent = (
        get("General", "AccentColor")
        or get("Colors:Selection", "BackgroundNormal")
        or get("Colors:View", "DecorationFocus")
    )

    colors = {
        "window_bg_color": window_bg,
        "window_fg_color": window_fg,
        "view_bg_color": view_bg,
        "view_fg_color": view_fg,
        "headerbar_bg_color": header_bg,
        "headerbar_fg_color": header_fg,
        "headerbar_backdrop_color": header_backdrop,
        "sidebar_bg_color": alt_bg,
        "sidebar_fg_color": window_fg,
        "dialog_bg_color": window_bg,
        "dialog_fg_color": window_fg,
        "popover_bg_color": alt_bg,
        "popover_fg_color": window_fg,
    }
    if accent is not None:
        colors["accent_bg_color"] = accent
        colors["accent_color"] = accent
        colors["accent_fg_color"] = (
            (0, 0, 0) if _luminance(accent) > 0.45 else (255, 255, 255)
        )
    for name, key in (
        ("success_color", "ForegroundPositive"),
        ("warning_color", "ForegroundNeutral"),
        ("error_color", "ForegroundNegative"),
    ):
        rgb = get("Colors:Window", key)
        if rgb is not None:
            colors[name] = rgb
    negative = get("Colors:Window", "ForegroundNegative")
    if negative is not None:
        colors["destructive_bg_color"] = negative
        colors["destructive_color"] = negative
    return {name: _hex(rgb) for name, rgb in colors.items()}


def kde_css(colors: dict) -> str:
    if not colors:
        return ""
    lines = [f"@define-color {name} {value};" for name, value in colors.items()]
    # The header sits in an Adw.ToolbarView, which draws top bars flat (window
    # colour); give it the KDE header colour like Plasma apps have.
    lines.append(
        "toolbarview > .top-bar {"
        " background-color: @headerbar_bg_color;"
        " color: @headerbar_fg_color; }"
    )
    lines.append(
        "toolbarview > .top-bar:backdrop {"
        " background-color: @headerbar_backdrop_color; }"
    )
    return "\n".join(lines) + "\n"


def _load_kde_colors() -> str:
    try:
        with open(_kdeglobals_path(), encoding="utf-8", errors="replace") as fh:
            colors = kde_colors(parse_kdeglobals(fh.read()))
    except OSError:
        return ""
    if not colors:
        return ""
    # Only apply when the KDE scheme agrees with libadwaita's light/dark state
    # (e.g. the user forced Light in Preferences while Plasma is dark).
    window_dark = _luminance(_kde_rgb_from_hex(colors["window_bg_color"])) < 0.5
    if window_dark != is_dark():
        return ""
    return kde_css(colors)


def _kde_rgb_from_hex(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# KDE window buttons
#
# On Plasma the GTK window buttons would otherwise be libadwaita's grey
# circles. When KWin uses an Aurorae (SVG) decoration we render that theme's
# close/minimize/maximize/restore images ourselves, so the buttons match the
# KWin title bars without relying on ~/.config/gtk-4.0 (which theme tools
# like to rewrite). Native decorations such as Breeze have no SVGs to borrow;
# the buttons are then left alone.
# ---------------------------------------------------------------------------

_BUTTON_STATES = (
    # (GTK state suffix, CSS pseudo-class, Aurorae element)
    ("normal", "", "active-center"),
    ("backdrop", ":backdrop", "inactive-center"),
    ("hover", ":hover", "hover-center"),
    ("active", ":active", "pressed-center"),
)
_RENDER_SCALE = 3  # stay crisp on HiDPI screens


def _kwinrc_path() -> str:
    return os.path.join(os.path.dirname(_kdeglobals_path()), "kwinrc")


def aurorae_theme_name(sections: dict):
    """Name of the active Aurorae theme from a parsed kwinrc, else None."""
    deco = sections.get("org.kde.kdecoration2", {})
    library = deco.get("library", "org.kde.kwin.aurorae")
    if library != "org.kde.kwin.aurorae":
        return None
    theme = deco.get("theme", "")
    prefix = "__aurorae__svg__"
    if theme.startswith(prefix):
        return theme[len(prefix):] or None
    return None


def _aurorae_theme_dir(name: str):
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for base in [data_home] + data_dirs.split(":"):
        if not base:
            continue
        path = os.path.join(base, "aurorae", "themes", name)
        if os.path.isdir(path):
            return path
    return None


def _aurorae_button_size(theme_dir: str, name: str) -> tuple:
    width = height = 16
    try:
        with open(os.path.join(theme_dir, name + "rc"), encoding="utf-8",
                  errors="replace") as fh:
            layout = parse_kdeglobals(fh.read()).get("Layout", {})
        width = int(layout.get("ButtonWidth", width))
        height = int(layout.get("ButtonHeight", height))
    except (OSError, ValueError):
        pass
    clamp = lambda v: max(10, min(28, v))  # noqa: E731
    return clamp(width), clamp(height)


def _render_aurorae_buttons(theme_dir: str, out_dir: str, size: tuple) -> dict:
    """Render button states to PNGs; returns {(button, state): path}."""
    try:
        import cairo

        gi.require_version("Rsvg", "2.0")
        from gi.repository import Rsvg
    except (ImportError, ValueError):
        return {}

    os.makedirs(out_dir, exist_ok=True)
    px_w, px_h = size[0] * _RENDER_SCALE, size[1] * _RENDER_SCALE
    rendered = {}
    for button in ("close", "minimize", "maximize", "restore"):
        svg = None
        for ext in (".svg", ".svgz"):
            candidate = os.path.join(theme_dir, button + ext)
            if os.path.isfile(candidate):
                svg = candidate
                break
        if svg is None:
            continue
        try:
            handle = Rsvg.Handle.new_from_file(svg)
        except Exception:
            continue
        for state, _pseudo, element in _BUTTON_STATES:
            if not handle.has_sub("#" + element):
                element = "active-center"
                if not handle.has_sub("#" + element):
                    break
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px_w, px_h)
            viewport = Rsvg.Rectangle()
            viewport.x, viewport.y = 0, 0
            viewport.width, viewport.height = px_w, px_h
            try:
                handle.render_element(cairo.Context(surface), "#" + element, viewport)
            except Exception:
                break
            path = os.path.join(out_dir, f"{button}-{state}.png")
            surface.write_to_png(path)
            rendered[(button, state)] = path
    return rendered


def titlebutton_css(images: dict, size: tuple) -> str:
    """CSS that paints window buttons with pre-rendered images."""
    from gi.repository import GLib

    def url(path):
        return GLib.filename_to_uri(path, None)

    lines = []
    for button in ("close", "minimize", "maximize"):
        if (button, "normal") not in images:
            continue
        for state, pseudo, _element in _BUTTON_STATES:
            path = images.get((button, state))
            if path is None:
                continue
            rule = f'background-image: url("{url(path)}");'
            if not pseudo:
                rule += (
                    f" background-size: {size[0]}px {size[1]}px;"
                    " background-repeat: no-repeat;"
                    " background-position: center;"
                    " background-color: transparent; box-shadow: none;"
                )
            lines.append(f"windowcontrols > button.{button}{pseudo} {{ {rule} }}")
            restore = images.get(("restore", state))
            if button == "maximize" and restore is not None:
                lines.append(
                    f"window.maximized windowcontrols > button.maximize{pseudo}"
                    f' {{ background-image: url("{url(restore)}"); }}'
                )
    if not lines:
        return ""
    # Hide libadwaita's symbolic glyphs; the images carry their own.
    lines.append(
        "windowcontrols > button.close > image,"
        " windowcontrols > button.minimize > image,"
        " windowcontrols > button.maximize > image { opacity: 0; }"
    )
    return "\n".join(lines) + "\n"


def _load_kde_titlebuttons() -> str:
    try:
        with open(_kwinrc_path(), encoding="utf-8", errors="replace") as fh:
            name = aurorae_theme_name(parse_kdeglobals(fh.read()))
    except OSError:
        return ""
    if not name or "/" in name or name.startswith("."):
        return ""
    theme_dir = _aurorae_theme_dir(name)
    if theme_dir is None:
        return ""
    from gi.repository import GLib

    size = _aurorae_button_size(theme_dir, name)
    out_dir = os.path.join(
        GLib.get_user_cache_dir(), "datamonitor", "titlebuttons", name
    )
    try:
        images = _render_aurorae_buttons(theme_dir, out_dir, size)
    except OSError:
        return ""
    return titlebutton_css(images, size)


def refresh_kde_colors(*_args) -> None:
    if _kde_provider is None:
        return
    css = _load_kde_colors() + _load_kde_titlebuttons()
    loader = getattr(_kde_provider, "load_from_string", None)
    if loader is not None:
        loader(css)
    else:  # pragma: no cover - older GTK
        _kde_provider.load_from_data(css.encode("utf-8"))


def _on_kdeglobals_changed(*_args) -> None:
    global _kde_reload_id
    from gi.repository import GLib

    # Plasma rewrites the file in several steps; reload once it settles.
    if _kde_reload_id:
        GLib.source_remove(_kde_reload_id)

    def reload():
        global _kde_reload_id
        _kde_reload_id = 0
        refresh_kde_colors()
        return False

    _kde_reload_id = GLib.timeout_add(300, reload)


def install_kde_colors(display=None) -> bool:
    """Follow the KDE colour scheme when running on Plasma.

    Returns True when KDE pickup is active. No-op elsewhere.
    """
    global _kde_provider, _kde_monitor
    if _kde_provider is not None:
        return True
    if not _running_kde():
        return False
    display = display or Gdk_display()
    _kde_provider = Gtk.CssProvider()
    refresh_kde_colors()
    Gtk.StyleContext.add_provider_for_display(
        display,
        _kde_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    try:
        Adw.StyleManager.get_default().connect("notify::dark", refresh_kde_colors)
    except Exception:  # pragma: no cover
        pass
    _kde_monitor = []
    try:
        from gi.repository import Gio

        for path in (_kdeglobals_path(), _kwinrc_path()):
            monitor = Gio.File.new_for_path(path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
            monitor.connect("changed", _on_kdeglobals_changed)
            _kde_monitor.append(monitor)
    except Exception:  # pragma: no cover - no live updates, colours still set
        pass
    return True
