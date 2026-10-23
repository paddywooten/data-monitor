"""Custom widgets: stat cards, charts."""

from __future__ import annotations

import cairo

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango  # noqa: E402

from . import theme, util  # noqa: E402

__all__ = ["StatCard", "SpeedGraph", "BarChart"]


# ==========================================================================
# stat cards
# ==========================================================================
class StatCard(Gtk.Box):
    """A little panel with a caption, a big number and a footnote."""

    def __init__(self, title: str, value: str = "–", subtitle: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("dw-card")
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.FILL)

        self._title = Gtk.Label(label=title.upper(), xalign=0)
        self._title.add_css_class("dw-card-title")
        self._value = Gtk.Label(label=value, xalign=0)
        self._value.add_css_class("dw-value")
        self._value.set_selectable(False)
        self._subtitle = Gtk.Label(label=subtitle, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._subtitle.add_css_class("dw-card-sub")

        self.append(self._title)
        self.append(self._value)
        self.append(self._subtitle)

    def set_value(self, text: str) -> None:
        self._value.set_text(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.set_text(text)

    def set_title(self, text: str) -> None:
        self._title.set_text(text.upper())

    def set_tone(self, tone: str | None) -> None:
        for cls in ("dw-down", "dw-warn", "dw-error", "dw-up", "dw-muted"):
            self._value.remove_css_class(cls)
        if tone:
            self._value.add_css_class(tone)


# ==========================================================================
# geometry helpers
# ==========================================================================
def nice_ceiling(value: float, minimum: float = 1000.0) -> float:
    """Round a bitrate up to something friendly for axis labels."""
    import math

    value = max(float(value), float(minimum))
    exponent = math.floor(math.log10(value))
    base = 10.0 ** exponent
    for step in (1.0, 2.0, 5.0, 10.0):
        if value <= step * base + 1e-9:
            return step * base
    return 10.0 * base


def _rounded_top(cr, x: float, y: float, w: float, h: float, radius: float) -> None:
    r = max(0.0, min(radius, w / 2.0, h))
    cr.new_path()
    cr.move_to(x, y + h)
    cr.line_to(x, y + r)
    cr.arc(x + r, y + r, r, -3.14159265, -1.57079633)
    cr.line_to(x + w - r, y)
    cr.arc(x + w - r, y + r, r, -1.57079633, 0.0)
    cr.line_to(x + w, y + h)
    cr.close_path()


# ==========================================================================
# live speed graph
# ==========================================================================
class SpeedGraph(Gtk.DrawingArea):
    """Rolling download / upload rate chart drawn with cairo."""

    def __init__(self, height: int = 260, samples: int = 90):
        super().__init__()
        self.add_css_class("dw-graph")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_content_height(height)
        self.set_draw_func(self._draw)
        self._samples = max(10, samples)
        self.series: list[tuple[float, float, float]] = []
        self.empty_text = "Waiting for the first sample…"
        self._unit_hint = "Mbps"

    # -- data -------------------------------------------------------------
    def push(self, ts: float, down: float, up: float) -> None:
        self.series.append((ts, down, up))
        overflow = len(self.series) - self._samples
        if overflow > 0:
            del self.series[:overflow]
        self.queue_draw()

    def set_capacity(self, samples: int) -> None:
        self._samples = max(10, int(samples))
        overflow = len(self.series) - self._samples
        if overflow > 0:
            del self.series[:overflow]
        self.queue_draw()

    def clear(self) -> None:
        self.series.clear()
        self.queue_draw()

    # -- drawing ----------------------------------------------------------
    def _draw(self, _area, cr, width: int, height: int) -> None:
        colors = theme.palette()
        left, right, top, bottom = 10.0, 62.0, 14.0, 22.0
        plot_w = float(width) - left - right
        plot_h = float(height) - top - bottom
        if plot_w < 40 or plot_h < 30:
            return

        data = self.series
        peak = 0.0
        for _, down, up in data:
            peak = max(peak, down, up)
        ymax = nice_ceiling(peak * 1.15, minimum=10_000.0)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5)

        # horizontal grid + y labels -------------------------------------
        steps = 4
        for i in range(steps + 1):
            y = top + plot_h * i / steps
            value = ymax * (1.0 - i / steps)
            cr.set_source_rgba(*colors["grid"])
            cr.set_line_width(1.0)
            cr.move_to(left, y + 0.5)
            cr.line_to(left + plot_w, y + 0.5)
            cr.stroke()
            label = util.format_rate(value)
            cr.set_source_rgba(*colors["dim"])
            ext = cr.text_extents(label)
            cr.move_to(left + plot_w + 9.0, y + ext.height / 2.0 + 3.5)
            cr.show_text(label)

        baseline = top + plot_h

        if len(data) >= 2:
            n = len(data)
            xs = [left + plot_w * i / (n - 1) for i in range(n)]

            for key, color, stroke in (("up", colors["up"], 1.4), ("down", colors["down"], 1.8)):
                # series rows are (timestamp, download, upload)
                index = 1 if key == "down" else 2
                values = [row[index] for row in data]

                # filled area
                cr.new_path()
                cr.move_to(xs[0], baseline)
                for x, val in zip(xs, values):
                    cr.line_to(x, baseline - (val / ymax) * plot_h)
                cr.line_to(xs[-1], baseline)
                cr.close_path()
                gradient = cairo.LinearGradient(0.0, top, 0.0, baseline)
                gradient.add_color_stop_rgba(0.0, color[0], color[1], color[2], 0.45)
                gradient.add_color_stop_rgba(1.0, color[0], color[1], color[2], 0.03)
                cr.set_source(gradient)
                cr.fill()

                # line on top
                cr.new_path()
                for i, (x, val) in enumerate(zip(xs, values)):
                    y = baseline - (val / ymax) * plot_h
                    if i == 0:
                        cr.move_to(x, y)
                    else:
                        cr.line_to(x, y)
                cr.set_source_rgba(color[0], color[1], color[2], 0.95)
                cr.set_line_width(stroke)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.stroke()

            # "now" edge
            cr.set_source_rgba(*colors["grid"])
            cr.set_line_width(1.0)
            cr.move_to(xs[-1] + 0.5, top)
            cr.line_to(xs[-1] + 0.5, baseline)
            cr.stroke()

            # x axis labels
            cr.set_font_size(10.5)
            cr.set_source_rgba(*colors["dim"])
            first = util.format_time(data[0][0])
            ext = cr.text_extents(first)
            cr.move_to(left, baseline + ext.height + 6.0)
            cr.show_text(first)
            now_text = "now"
            ext = cr.text_extents(now_text)
            cr.move_to(left + plot_w - ext.width, baseline + ext.height + 6.0)
            cr.show_text(now_text)
        else:
            cr.set_font_size(12.5)
            cr.set_source_rgba(*colors["dim"])
            ext = cr.text_extents(self.empty_text)
            cr.move_to(left + (plot_w - ext.width) / 2.0, top + plot_h / 2.0)
            cr.show_text(self.empty_text)


# ==========================================================================
# history bar chart
# ==========================================================================
class BarChart(Gtk.DrawingArea):
    """Daily totals bar chart; colour reflects the daily limit state."""

    def __init__(self, height: int = 210):
        super().__init__()
        self.add_css_class("dw-graph")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_content_height(height)
        self.set_draw_func(self._draw)
        # items: (label, value_bytes, tone)  tone in ok / warn / error / active
        self.items: list[tuple[str, float, str]] = []
        self.empty_text = "No samples for this range yet."
        self._hover = -1

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_items(self, items: list[tuple[str, float, str]]) -> None:
        self.items = list(items)
        self._hover = -1
        self.set_tooltip_text(None)
        self.queue_draw()

    # -- hover ------------------------------------------------------------
    def _index_at(self, x: float, y: float, width: int) -> int:
        if not self.items:
            return -1
        left, right, top, bottom = 10.0, 52.0, 16.0, 24.0
        plot_w = float(width) - left - right
        n = len(self.items)
        slot = plot_w / n
        i = int((x - left) / slot) if slot > 0 else -1
        if 0 <= i < n and left <= x <= left + plot_w and y >= top:
            return i
        return -1

    def _on_motion(self, _ctrl, x: float, y: float) -> None:
        width = self.get_width()
        index = self._index_at(x, y, width)
        if index != self._hover:
            self._hover = index
            if index >= 0:
                label, value, _ = self.items[index]
                self.set_tooltip_text(f"{label}: {util.format_bytes(value)}")
            else:
                self.set_tooltip_text(None)
            self.queue_draw()

    def _on_leave(self, _ctrl) -> None:
        if self._hover >= 0:
            self._hover = -1
            self.set_tooltip_text(None)
            self.queue_draw()

    # -- drawing ----------------------------------------------------------
    def _draw(self, _area, cr, width: int, height: int) -> None:
        colors = theme.palette()
        left, right, top, bottom = 10.0, 52.0, 16.0, 26.0
        plot_w = float(width) - left - right
        plot_h = float(height) - top - bottom
        if plot_w < 40 or plot_h < 30:
            return

        if not self.items:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(12.5)
            cr.set_source_rgba(*colors["dim"])
            ext = cr.text_extents(self.empty_text)
            cr.move_to(left + (plot_w - ext.width) / 2.0, top + plot_h / 2.0)
            cr.show_text(self.empty_text)
            return

        peak = max(v for _, v, _ in self.items)
        ymax = nice_ceiling(max(peak * 1.1, 1_000_000.0), minimum=1_000_000.0)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5)

        for i in range(5):
            y = top + plot_h * i / 4
            cr.set_source_rgba(*colors["grid"])
            cr.set_line_width(1.0)
            cr.move_to(left, y + 0.5)
            cr.line_to(left + plot_w, y + 0.5)
            cr.stroke()
            label = util.format_bytes(ymax * (1.0 - i / 4.0))
            cr.set_source_rgba(*colors["dim"])
            ext = cr.text_extents(label)
            cr.move_to(left + plot_w + 9.0, y + ext.height / 2.0 + 3.5)
            cr.show_text(label)

        baseline = top + plot_h
        n = len(self.items)
        gap = 3.0 if n <= 40 else 2.0
        slot = plot_w / n
        bar_w = max(2.0, slot - gap)

        label_every = max(1, n // 7)

        for i, (label, value, tone) in enumerate(self.items):
            x = left + slot * i + (slot - bar_w) / 2.0
            h = 0.0 if ymax <= 0 else (value / ymax) * plot_h
            if value > 0:
                h = max(h, 2.0)
            color = {
                "warn": colors["warn"],
                "error": colors["error"],
                "active": colors["up"],
            }.get(tone, colors["down"])
            if i == self._hover:
                cr.set_source_rgba(*colors["hover"])
                cr.rectangle(left + slot * i, top - 4, slot, plot_h + 4)
                cr.fill()
            if h > 0:
                _rounded_top(cr, x, baseline - h, bar_w, h, min(4.0, bar_w / 2.0))
                cr.set_source_rgba(color[0], color[1], color[2], 0.92)
                cr.fill()

            if i % label_every == 0 or i == n - 1:
                cr.set_source_rgba(*colors["dim"])
                cr.set_font_size(10.0)
                ext = cr.text_extents(label)
                tx = x + bar_w / 2.0 - ext.width / 2.0
                cr.move_to(max(0.0, tx), baseline + ext.height + 7.0)
                cr.show_text(label)
