"""The Apps page: top data consumers, per-app limits and whitelisting.

The numbers come from :mod:`datawatch.apptrack` (TCP socket counters);
enforcement (pause / resume) lives in :mod:`datawatch.enforce`.
Whitelisted apps are never paused, whatever their limits say.
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from . import quota, util  # noqa: E402
from .settings import _spin_row, _switch_row  # noqa: E402
from .widgets import BarChart  # noqa: E402

APP_RANGES = ("Today", "This billing cycle", "All time")
COLUMN_WIDTH = 120
MAX_CHART_APPS = 8

# chart tone -> CSS class (None = default colour)
_TONE_CSS = {"error": "dw-error", "warn": "dw-warn", "active": "dw-up", "ok": None}


def _label(text: str, css: str | None = None, xalign: float = 0.0) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        widget.add_css_class(css)
    return widget


def _header_row(values) -> Gtk.Grid:
    grid = Gtk.Grid(
        column_spacing=12, margin_start=10, margin_end=10,
        margin_top=4, margin_bottom=4,
    )
    grid.set_hexpand(True)
    for i, text in enumerate(values):
        label = _label(
            text.upper(), css="dw-cell-header", xalign=0 if i == 0 else 1
        )
        if i == 0:
            label.set_hexpand(True)
        else:
            label.set_size_request(COLUMN_WIDTH, -1)
        grid.attach(label, i, 0, 1, 1)
    return grid


class AppsPage(Gtk.Box):
    """Top consumers chart + per-app table with limits and whitelist."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window = window  # config / storage / sampler / enforcer access
        self._rows: dict[str, dict] = {}
        self._scope = 0
        self._build()

    # =====================================================================
    # construction
    # =====================================================================
    def _build(self) -> None:
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.scope_drop = Gtk.DropDown(
            model=Gtk.StringList.new(list(APP_RANGES))
        )
        self.scope_drop.set_selected(0)
        self.scope_drop.connect("notify::selected", self._on_scope)
        hint = _label(
            "per-app from TCP sockets · UDP lands in “Other”",
            css="dw-caption",
            xalign=1,
        )
        hint.set_hexpand(True)
        top.append(self.scope_drop)
        top.append(hint)

        self.pause_banner = Adw.Banner(title="", button_label="Resume all")
        self.pause_banner.connect("button-clicked", self._on_resume_all)
        self.pause_banner.set_revealed(False)

        self.bars = BarChart(height=170)
        self.bars.set_vexpand(False)

        head = _header_row(("App", "Today", "This cycle", "All time", "Status"))
        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.table.add_css_class("dw-table")
        self.table.append(head)
        self.table.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.table.append(self.rows_box)
        scroll = Gtk.ScrolledWindow(
            child=self.table,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
        )

        # Empty state (tracking off / no ss / no traffic yet).
        self.empty = Adw.StatusPage()
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_valign(Gtk.Align.CENTER)
        self.empty_button = Gtk.Button(label="Open Preferences")
        self.empty_button.add_css_class("pill")
        self.empty_button.connect(
            "clicked", lambda *_: self.window.open_settings()
        )
        empty_box.append(self.empty_button)
        self.empty.set_child(empty_box)

        note = _label(
            "Per-app figures come from TCP sockets; UDP, other users and "
            "protocol overhead land in “Other”.",
            css="dw-note",
        )
        note.set_wrap(True)

        self.append(top)
        self.append(self.pause_banner)
        self.append(self.bars)
        self.append(scroll)
        self.append(self.empty)
        self.append(note)
        self._note = note

    def _on_scope(self, drop, _pspec) -> None:
        selected = drop.get_selected()
        if selected != Gtk.INVALID_LIST_POSITION:
            self._scope = int(selected)
        self.refresh()

    # =====================================================================
    # data helpers
    # =====================================================================
    @staticmethod
    def _tone(app, day, cycle, limits, paused, warn) -> str:
        """Chart/status colour: paused > over limit > near limit > ok."""
        if app in paused:
            return "active"
        lim = limits.get(app) or {}
        daily = int(float(lim.get("daily_mb", 0)) * 1_000_000)
        cyc = int(float(lim.get("cycle_mb", 0)) * 1_000_000)
        over = (daily > 0 and day.get(app, 0) >= daily) or (
            cyc > 0 and cycle.get(app, 0) >= cyc
        )
        if over:
            return "error"
        near = (0 < daily and day.get(app, 0) >= daily * warn) or (
            0 < cyc and cycle.get(app, 0) >= cyc * warn
        )
        return "warn" if near else "ok"

    @staticmethod
    def _limit_view(app, day, cycle, limits) -> tuple[float, int] | None:
        """Best ``(fraction, limit_bytes)`` across the app's set limits."""
        lim = limits.get(app) or {}
        daily = int(float(lim.get("daily_mb", 0)) * 1_000_000)
        cyc = int(float(lim.get("cycle_mb", 0)) * 1_000_000)
        best: tuple[float, int] | None = None
        if daily > 0:
            best = (day.get(app, 0) / daily, daily)
        if cyc > 0:
            frac = cycle.get(app, 0) / cyc
            if best is None or frac > best[0]:
                best = (frac, cyc)
        return best

    def _status(
        self, app, day, cycle, limits, whitelist, paused, warn
    ) -> tuple[str, str | None, str | None]:
        rec = paused.get(app)
        if rec:
            return (
                f"Paused — {rec['reason']}",
                "dw-error",
                "Resumes at the next reset, or from this menu.",
            )
        view = self._limit_view(app, day, cycle, limits)
        limit_text = None
        if view is not None:
            frac, limit = view
            limit_text = f"{util.format_percent(frac, 0)} of {util.format_bytes(limit)}"
        if app in whitelist:
            tip = "Never paused automatically."
            if limit_text:
                tip += f" Currently at {limit_text}."
            return ("Whitelisted", "dw-up", tip)
        if limit_text:
            frac, _limit = view
            tone = _TONE_CSS[
                "error" if frac >= 1 else ("warn" if frac >= warn else "ok")
            ]
            return (limit_text, tone, None)
        return ("—", "dw-muted", None)

    # =====================================================================
    # refresh
    # =====================================================================
    def refresh(self) -> None:
        win = self.window
        cfg, storage, sampler = win.config, win.storage, win.sampler
        now = time.time()
        horizon = int(now) + 1
        day_start, _ = quota.day_bounds(now)
        cycle_start, _ = quota.cycle_bounds(now, cfg.cycle_day)

        day = {
            app: rx + tx
            for app, rx, tx in storage.app_totals_range(day_start, horizon)
        }
        cycle = {
            app: rx + tx
            for app, rx, tx in storage.app_totals_range(cycle_start, horizon)
        }
        life = {app: rx + tx for app, (rx, tx) in storage.app_totals_all().items()}
        paused = win.enforcer.paused()
        whitelist = set(cfg.app_whitelist)
        limits = cfg.app_limits
        warn = cfg.warn_percent / 100.0

        known = (
            set(day) | set(cycle) | set(life)
            | set(sampler.tracked_apps)
            | set(limits) | whitelist | set(paused)
        )

        # ---- rows -------------------------------------------------------
        if set(self._rows) != known:
            self._rebuild_rows(known, life)
        for app in self._rows:
            self._update_row(app, day, cycle, life, limits, whitelist, paused, warn)

        # ---- chart (follows the scope picker) ---------------------------
        usage, iface_total, scope_label = self._scope_data(
            storage, sampler, now, day, cycle, life
        )
        items: list[tuple[str, float, str]] = []
        tooltips: list[str] = []
        ranked = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)
        for app, total in ranked[:MAX_CHART_APPS]:
            label = app if len(app) <= 14 else app[:13] + "…"
            items.append(
                (label, total, self._tone(app, day, cycle, limits, paused, warn))
            )
            tooltips.append(f"{app}: {util.format_bytes(total)} {scope_label}")
        other = max(0, iface_total - sum(usage.values()))
        if other > 0:
            items.append(("Other", other, "ok"))
            tooltips.append(
                f"Other: {util.format_bytes(other)} — UDP, other users, "
                "protocol overhead"
            )
        self.bars.set_items(items, tooltips=tooltips)

        # ---- paused banner ---------------------------------------------
        if paused:
            names = sorted(paused)
            shown = ", ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else "")
            self.pause_banner.set_title(
                f"{len(names)} app{'' if len(names) == 1 else 's'} paused "
                f"({shown}) — limit reached"
            )
            self.pause_banner.set_revealed(True)
        else:
            self.pause_banner.set_revealed(False)

        # ---- empty states ----------------------------------------------
        has_data = bool(known)
        self.table.set_visible(has_data)
        self.bars.set_visible(has_data)
        self._note.set_visible(has_data)
        if not has_data:
            self._configure_empty()
            self.empty.set_visible(True)
        else:
            self.empty.set_visible(False)

    def _scope_data(self, storage, sampler, now, day, cycle, life):
        cfg = self.window.config
        if self._scope == 0:
            start, _ = quota.day_bounds(now)
            rx, tx = storage.totals(start, int(now) + 1, sampler.tracked)
            return day, rx + tx, "today"
        if self._scope == 1:
            start, _ = quota.cycle_bounds(now, cfg.cycle_day)
            rx, tx = storage.totals(start, int(now) + 1, sampler.tracked)
            return cycle, rx + tx, "this cycle"
        rx, tx = storage.all_time()
        return life, rx + tx, "all time"

    def _configure_empty(self) -> None:
        cfg = self.window.config
        tracker = getattr(self.window.sampler, "tracker", None)
        if not cfg.track_apps:
            self.empty.set_title("Per-app tracking is off")
            self.empty.set_description(
                "Turn on “Track per-app usage” in Preferences to see which "
                "programs use your data."
            )
            self.empty_button.set_visible(True)
        elif tracker is None or not tracker.available:
            self.empty.set_title("iproute2 not found")
            self.empty.set_description(
                "Install the iproute2 package (it provides the ss tool) to "
                "attribute traffic to programs."
            )
            self.empty_button.set_visible(False)
        else:
            self.empty.set_title("No per-app data yet")
            self.empty.set_description(
                "Programs appear here within a few seconds of them sending "
                "or receiving data."
            )
            self.empty_button.set_visible(False)

    # =====================================================================
    # rows
    # =====================================================================
    def _rebuild_rows(self, known: set[str], life: dict) -> None:
        for parts in self._rows.values():
            self.rows_box.remove(parts["row"])
        self._rows.clear()
        for app in sorted(known, key=lambda a: (-life.get(a, 0), a)):
            self._rows[app] = self._create_row(app)

    def _create_row(self, app: str) -> dict:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
            margin_start=10, margin_end=10,
            margin_top=8, margin_bottom=8,
        )
        outer.set_hexpand(True)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_hexpand(True)
        name = _label(app, css="heading")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        sub = _label("", css="dw-caption")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        left.append(name)
        left.append(sub)

        today = _label("–", css="dw-cell", xalign=1)
        cycle = _label("–", css="dw-cell", xalign=1)
        alltime = _label("–", css="dw-cell", xalign=1)
        for lbl in (today, cycle, alltime):
            lbl.set_size_request(COLUMN_WIDTH, -1)

        status = _label("–", css="dw-cell", xalign=1)
        status.set_size_request(COLUMN_WIDTH, -1)
        status.set_ellipsize(Pango.EllipsizeMode.END)

        menu = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text=f"Options for {app}",
            valign=Gtk.Align.CENTER,
        )
        popover, clear_btn, white_btn, resume_btn = self._row_menu(app)
        menu.set_popover(popover)

        outer.append(left)
        outer.append(today)
        outer.append(cycle)
        outer.append(alltime)
        outer.append(status)
        outer.append(menu)
        self.rows_box.append(outer)

        return {
            "row": outer, "name": name, "sub": sub,
            "today": today, "cycle": cycle, "all": alltime,
            "status": status, "popover": popover,
            "clear": clear_btn, "whitelist": white_btn, "resume": resume_btn,
        }

    def _row_menu(self, app: str):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        def button(text: str, handler) -> Gtk.Button:
            btn = Gtk.Button(label=text, halign=Gtk.Align.FILL)
            btn.add_css_class("flat")
            btn.connect("clicked", handler, app)
            box.append(btn)
            return btn

        button("Set or change limits…", self._on_set_limit)
        clear_btn = button("Clear limits", self._on_clear_limits)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        white_btn = button("Whitelist — never pause", self._on_toggle_whitelist)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        resume_btn = button("Resume now", self._on_resume_app)

        popover = Gtk.Popover()
        popover.set_child(box)
        return popover, clear_btn, white_btn, resume_btn

    def _update_row(
        self, app, day, cycle, life, limits, whitelist, paused, warn
    ) -> None:
        p = self._rows[app]
        p["today"].set_text(util.format_bytes(day.get(app, 0)))
        p["cycle"].set_text(util.format_bytes(cycle.get(app, 0)))
        p["all"].set_text(util.format_bytes(life.get(app, 0)))

        lim = limits.get(app) or {}
        parts = []
        if float(lim.get("daily_mb", 0)) > 0:
            parts.append(f"daily {util.format_bytes(float(lim['daily_mb']) * 1e6)}")
        if float(lim.get("cycle_mb", 0)) > 0:
            parts.append(f"cycle {util.format_bytes(float(lim['cycle_mb']) * 1e6)}")
        p["sub"].set_text(" · ".join(parts))

        text, tone, tip = self._status(
            app, day, cycle, limits, whitelist, paused, warn
        )
        for cls in ("dw-error", "dw-warn", "dw-up", "dw-muted"):
            p["status"].remove_css_class(cls)
        if tone:
            p["status"].add_css_class(tone)
        p["status"].set_text(text)
        p["status"].set_tooltip_text(tip)

        p["clear"].set_sensitive(bool(lim))
        p["whitelist"].set_label(
            "✓ Whitelisted — never pause" if app in whitelist
            else "Whitelist — never pause"
        )
        p["resume"].set_sensitive(app in paused)

    # =====================================================================
    # row menu actions
    # =====================================================================
    def _toast(self, text: str) -> None:
        self.window.toast_overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _on_set_limit(self, _btn, app: str) -> None:
        self._rows[app]["popover"].popdown()
        LimitDialog(self.window, app).present()

    def _on_clear_limits(self, _btn, app: str) -> None:
        self._rows[app]["popover"].popdown()
        cfg = self.window.config
        cfg.app_limits.pop(app, None)
        cfg.save()
        self.window.storage.clear_app_alerts(app)
        self.window._enforce()
        self.refresh()
        self._toast(f"Limits cleared for {app}")

    def _on_toggle_whitelist(self, _btn, app: str) -> None:
        self._rows[app]["popover"].popdown()
        cfg = self.window.config
        listed = set(cfg.app_whitelist)
        if app in listed:
            listed.discard(app)
            message = f"{app} can be paused again"
        else:
            listed.add(app)
            message = f"{app} will never be paused"
        cfg.app_whitelist = sorted(listed)
        cfg.save()
        self.window._enforce()  # an already-paused app resumes right away
        self.refresh()
        self._toast(message)

    def _on_resume_app(self, _btn, app: str) -> None:
        self._rows[app]["popover"].popdown()
        self.window.enforcer.resume_now(app)
        self.refresh()
        self._toast(f"{app} resumed — stays running until tomorrow")

    def _on_resume_all(self, _banner) -> None:
        self.window.enforcer.resume_all(manual=True)
        self.refresh()
        self._toast("All paused apps resumed")


class LimitDialog(Adw.Window):
    """Per-app daily / cycle limits + whitelist switch."""

    def __init__(self, window, app: str):
        super().__init__(
            application=window.get_application(),
            title=f"Limits for {app}",
            modal=True,
            default_width=440,
            default_height=440,
        )
        self.window = window
        self.app = app
        self.set_transient_for(window)
        cfg = window.config
        limits = cfg.app_limits.get(app, {})

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Gtk.Label(label=f"Limits for {app}", css_classes=["heading"])
        )
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save.connect("clicked", self._save)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Data limits",
            description="The app is paused automatically when it reaches a "
            "limit. 0 = no limit. Whitelisted apps are never paused.",
        )
        self.row_daily = _spin_row(
            "Daily limit",
            "Pause this app after this much in one day",
            0, 1_000_000,
            float(limits.get("daily_mb", 0)),
            digits=0, suffix="MB",
        )
        self.row_cycle = _spin_row(
            "Billing-cycle limit",
            "Pause this app after this much in one billing cycle",
            0, 1_000_000,
            float(limits.get("cycle_mb", 0)),
            digits=0, suffix="MB",
        )
        self.row_whitelist = _switch_row(
            "Whitelist this app",
            "Never pause it automatically — not for its own limits, "
            "not when the overall cap is hit",
            app in cfg.app_whitelist,
        )
        group.add(self.row_daily)
        group.add(self.row_cycle)
        group.add(self.row_whitelist)
        page.add(group)
        toolbar.set_content(page)
        self.set_content(toolbar)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    def _on_key(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _save(self, *_args) -> None:
        cfg = self.window.config
        daily = float(self.row_daily.get_value())
        cycle = float(self.row_cycle.get_value())
        if daily > 0 or cycle > 0:
            cfg.app_limits[self.app] = {"daily_mb": daily, "cycle_mb": cycle}
        else:
            cfg.app_limits.pop(self.app, None)

        listed = set(cfg.app_whitelist)
        if self.row_whitelist.get_active():
            listed.add(self.app)
        else:
            listed.discard(self.app)
        cfg.app_whitelist = sorted(listed)
        cfg.save()

        # Let the new rules apply immediately (and re-notify when they bite).
        self.window.storage.clear_app_alerts(self.app)
        self.window._enforce()
        self.window.apps_page.refresh()
        self.window.toast_overlay.add_toast(
            Adw.Toast(title=f"Limits saved for {self.app}", timeout=3)
        )
        self.close()
