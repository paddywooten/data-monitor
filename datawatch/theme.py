"""Stylesheet + colour palettes for the GTK4 UI."""

from __future__ import annotations

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
