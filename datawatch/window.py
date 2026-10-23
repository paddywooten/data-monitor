"""The main dashboard window."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import netstat, quota, theme, util  # noqa: E402
from . import APP_NAME  # noqa: E402
from .apps import AppsPage  # noqa: E402
from .enforce import Enforcer  # noqa: E402
from .settings import SettingsWindow  # noqa: E402
from .widgets import BarChart, SpeedGraph, StatCard  # noqa: E402

HISTORY_RANGES = ("Last 7 days", "Last 30 days", "This billing cycle", "This year")
COLUMN_WIDTH = 120


def _label(text: str, css: str | None = None, xalign: float = 0.0) -> Gtk.Label:
    kwargs = {"label": text, "xalign": xalign}
    widget = Gtk.Label(**kwargs)
    if css:
        widget.add_css_class(css)
    return widget


def _table_row(values, header: bool = False, tones=None) -> Gtk.Grid:
    """One aligned row of a table (column 0 stretches, the rest right-align)."""
    grid = Gtk.Grid(column_spacing=12, margin_start=10, margin_end=10,
                    margin_top=4, margin_bottom=4)
    grid.set_hexpand(True)
    for i, text in enumerate(values):
        label = _label(
            text.upper() if header else text,
            css="dw-cell-header" if header else "dw-cell",
            xalign=0 if i == 0 else 1,
        )
        if i == 0:
            label.set_hexpand(True)
        else:
            label.set_size_request(COLUMN_WIDTH, -1)
        if tones and tones[i]:
            label.add_css_class(tones[i])
        grid.attach(label, i, 0, 1, 1)
    return grid


class MainWindow(Adw.ApplicationWindow):
    """Dashboard: live speeds, quota panel, history and per-interface stats."""

    def __init__(self, app, config, storage, sampler, enforcer=None):
        super().__init__(
            application=app,
            title=APP_NAME,
            default_width=1040,
            default_height=780,
        )
        self.config = config
        self.storage = storage
        self.sampler = sampler
        # Fallback keeps old test harnesses working without an enforcer.
        self.enforcer = enforcer or Enforcer(config, storage)

        self._settings: SettingsWindow | None = None
        self._background_hinted = False
        self._updating_switches = False
        self._iface_rows: dict[str, dict] = {}
        self._history_range = 1

        self._build()

        self.connect("close-request", self._on_close_request)
        self.sampler.start()
        self.graph.set_capacity(
            int(self.config.graph_window / max(1.0, self.config.poll_interval))
        )

        self._refresh_totals()
        self._refresh_interfaces()
        self._refresh_history()
        self.apps_page.refresh()
        self._enforce()

        GLib.timeout_add_seconds(5, self._on_totals_timer)
        GLib.timeout_add_seconds(30, self._on_maintenance_timer)

    # =====================================================================
    # UI construction
    # =====================================================================
    def _build(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar)

        header = Adw.HeaderBar()
        self.header_rate = _label("↓ –     ↑ –", css="dw-legend")
        self.header_rate.set_margin_start(8)
        header.pack_start(self.header_rate)

        self.stack = Adw.ViewStack()
        self.stack.set_enable_transitions(True)
        self.stack.set_vexpand(True)

        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        gear = Gtk.Button(
            icon_name="preferences-system-symbolic",
            tooltip_text="Preferences",
        )
        gear.connect("clicked", lambda *_: self.open_settings())
        header.pack_end(gear)

        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About Datawatch", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            popover=Gtk.PopoverMenu.new_from_model(menu),
        )
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)

        # ---- content ----------------------------------------------------
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("dw-page")

        self.banner = Adw.Banner(title="", button_label="Adjust")
        self.banner.connect("button-clicked", lambda *_: self.open_settings())
        self.banner.set_revealed(False)
        content.append(self.banner)

        content.append(self._build_quota_panel())
        content.append(self._build_overview())
        content.append(self.stack)
        toolbar.set_content(content)

        self.stack.add_titled_with_icon(
            self._build_overview_page(), "overview", "Overview", "view-grid-symbolic"
        )
        self.stack.add_titled_with_icon(
            self._build_history_page(), "history", "History", "document-open-recent-symbolic"
        )
        self.apps_page = AppsPage(self)
        self.stack.add_titled_with_icon(
            self.apps_page, "apps", "Apps", "system-run-symbolic"
        )
        self.stack.add_titled_with_icon(
            self._build_interfaces_page(), "interfaces", "Interfaces",
            "network-wireless-symbolic",
        )
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

    def _build_quota_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.add_css_class("dw-quota")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = _label("Billing cycle", css="dw-heading")
        title.set_hexpand(True)
        self.quota_dates = _label("", css="dw-caption", xalign=1)
        top.append(title)
        top.append(self.quota_dates)

        self.quota_bar = Gtk.ProgressBar()
        self.quota_bar.set_show_text(True)
        self.quota_bar.set_hexpand(True)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.quota_detail = _label("", css="dw-caption")
        self.quota_detail.set_hexpand(True)
        self.quota_pct = _label("", css="dw-heading", xalign=1)
        bottom.append(self.quota_detail)
        bottom.append(self.quota_pct)

        panel.append(top)
        panel.append(self.quota_bar)
        panel.append(bottom)
        return panel

    def _build_overview(self) -> Gtk.Grid:
        """The row of stat cards that sits above the stack."""
        grid = Gtk.Grid(column_homogeneous=True, row_spacing=12, column_spacing=12)
        self.card_down = StatCard("Download now")
        self.card_up = StatCard("Upload now")
        self.card_today = StatCard("Today")
        self.card_cycle = StatCard("This cycle")
        self.card_remaining = StatCard("Remaining")
        self.card_total = StatCard("All time")
        for i, card in enumerate(
            (self.card_down, self.card_up, self.card_today,
             self.card_cycle, self.card_remaining, self.card_total)
        ):
            grid.attach(card, i % 3, i // 3, 1, 1)
        return grid

    def _build_overview_page(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_hexpand(True)
        page.set_vexpand(True)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        down = _label("●  Download", css="dw-legend")
        down.add_css_class("dw-down")
        up = _label("●  Upload", css="dw-legend")
        up.add_css_class("dw-up")
        self.graph_hint = _label("", css="dw-legend", xalign=1)
        self.graph_hint.set_hexpand(True)
        legend.append(down)
        legend.append(up)
        legend.append(self.graph_hint)

        self.graph = SpeedGraph(height=280)
        self.graph.set_vexpand(True)
        self.graph_hint.set_text(f"last {util.format_duration(self.config.graph_window)}")

        page.append(legend)
        page.append(self.graph)
        return page

    def _build_history_page(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_hexpand(True)
        page.set_vexpand(True)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.range_drop = Gtk.DropDown(
            model=Gtk.StringList.new(list(HISTORY_RANGES))
        )
        self.range_drop.set_selected(self._history_range)
        self.range_drop.connect("notify::selected", self._on_range_changed)
        self.history_total = _label("", css="dw-caption", xalign=1)
        self.history_total.set_hexpand(True)
        top.append(self.range_drop)
        top.append(self.history_total)

        self.bars = BarChart(height=195)
        self.bars.set_vexpand(True)

        self.history_table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.history_table.add_css_class("dw-table")
        self.history_table.append(
            _table_row(("Date", "Download", "Upload", "Total"), header=True)
        )
        self.history_table.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.history_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.history_table.append(self.history_rows)

        # The table scrolls on its own so the range picker and the chart stay
        # put instead of pushing 30 rows below the fold.
        history_scroll = Gtk.ScrolledWindow(
            child=self.history_table,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
        )

        self.history_empty = Adw.StatusPage(
            title="No usage recorded yet",
            description="Datawatch samples your interfaces every couple of seconds. "
            "Come back once some traffic has flowed.",
        )
        self.history_empty.set_vexpand(True)

        page.append(top)
        page.append(self.bars)
        page.append(history_scroll)
        page.append(self.history_empty)
        return page

    def _build_interfaces_page(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_hexpand(True)
        page.set_vexpand(True)

        note = _label(
            "Only switched-on interfaces are counted toward your limits and totals.",
            css="dw-note",
        )
        note.set_wrap(True)

        head = _table_row(
            ("Interface", "Rate now", "Today / cycle / all time", "Counted"),
            header=True,
        )
        self.iface_table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.iface_table.add_css_class("dw-table")
        self.iface_table.append(head)
        self.iface_table.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.iface_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.iface_table.append(self.iface_rows_box)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button(label="Rescan interfaces")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self._refresh_interfaces())
        foot_note = _label(
            "Interfaces can appear and disappear (VPN, dock, tethering).",
            css="dw-note",
        )
        foot_note.set_hexpand(True)
        footer.append(refresh)
        footer.append(foot_note)

        iface_scroll = Gtk.ScrolledWindow(
            child=self.iface_table,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
        )

        page.append(note)
        page.append(iface_scroll)
        page.append(footer)
        return page

    # =====================================================================
    # live sample callback (every poll interval)
    # =====================================================================
    def on_sample(self, sampler) -> None:
        down = util.format_rate(sampler.down_bps)
        up = util.format_rate(sampler.up_bps)
        self.header_rate.set_text(f"↓ {down}     ↑ {up}")

        self.card_down.set_value(down)
        self.card_down.set_subtitle(f"peak {util.format_rate(sampler.peak_down)} today")
        self.card_down.set_tone("dw-down" if sampler.down_bps > 0 else None)
        self.card_up.set_value(up)
        self.card_up.set_subtitle(f"peak {util.format_rate(sampler.peak_up)} today")
        self.card_up.set_tone("dw-up" if sampler.up_bps > 0 else None)

        self.graph.push(time.time(), sampler.down_bps, sampler.up_bps)

        if self.stack.get_visible_child_name() == "interfaces":
            self._update_interface_rates()

    # =====================================================================
    # slower totals refresh (every 5 seconds)
    # =====================================================================
    def _enforce(self) -> None:
        """Reconcile pause/resume rules; never let this kill the timer."""
        try:
            self.enforcer.evaluate(self.sampler)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_totals_timer(self) -> bool:
        self._enforce()
        self._refresh_totals()
        if self.stack.get_visible_child_name() == "interfaces":
            self._refresh_interfaces()
        elif self.stack.get_visible_child_name() == "apps":
            self.apps_page.refresh()
        return GLib.SOURCE_CONTINUE

    def _on_maintenance_timer(self) -> bool:
        if self.stack.get_visible_child_name() == "history":
            self._refresh_history()
        return GLib.SOURCE_CONTINUE

    def _refresh_totals(self) -> None:
        now = time.time()
        cfg = self.config
        tracked = self.sampler.tracked

        day_start, day_end = quota.day_bounds(now)
        cycle_start, cycle_end = quota.cycle_bounds(now, cfg.cycle_day)

        today_rx, today_tx = self.storage.totals(day_start, day_end, tracked)
        cycle_rx, cycle_tx = self.storage.totals(cycle_start, int(now) + 1, tracked)
        lifetime_rx, lifetime_tx = self.storage.all_time()

        today = today_rx + today_tx
        cycle = cycle_rx + cycle_tx
        lifetime = lifetime_rx + lifetime_tx

        cycle_limit = cfg.cycle_limit_bytes()
        day_limit = cfg.day_limit_bytes()
        warn = cfg.warn_percent / 100.0

        # --- stat cards ---------------------------------------------------
        if day_limit > 0:
            self.card_today.set_subtitle(
                f"{util.format_percent(today / day_limit)} of "
                f"{util.format_bytes(day_limit)} daily limit"
            )
            self.card_today.set_tone(
                "dw-error" if today >= day_limit
                else ("dw-warn" if today >= day_limit * warn else None)
            )
        else:
            self.card_today.set_subtitle("no daily limit set")
            self.card_today.set_tone(None)
        self.card_today.set_value(util.format_bytes(today))

        self.card_cycle.set_value(util.format_bytes(cycle))
        self.card_cycle.set_subtitle(quota.cycle_label(cycle_start, cycle_end))
        self.card_cycle.set_tone(
            "dw-error" if 0 < cycle_limit <= cycle
            else ("dw-warn" if cycle_limit and cycle >= cycle_limit * warn else None)
        )

        if cycle_limit > 0:
            left = max(0, cycle_limit - cycle)
            self.card_remaining.set_value(util.format_bytes(left))
            self.card_remaining.set_subtitle(
                f"of {util.format_bytes(cycle_limit)} · resets in "
                f"{util.format_duration(cycle_end - now)}"
            )
            self.card_remaining.set_tone(
                "dw-error" if left == 0 else ("dw-warn" if cycle >= cycle_limit * warn else None)
            )
        else:
            self.card_remaining.set_value("Unlimited")
            self.card_remaining.set_subtitle(
                f"cycle resets in {util.format_duration(cycle_end - now)}"
            )
            self.card_remaining.set_tone(None)

        self.card_total.set_value(util.format_bytes(lifetime))
        first = self.storage.first_sample()
        if first:
            self.card_total.set_subtitle(
                f"since {util.format_date(first, '%b %d, %Y')}"
            )
        else:
            self.card_total.set_subtitle("waiting for the first sample")

        # --- quota panel --------------------------------------------------
        self.quota_dates.set_text(
            f"{quota.cycle_label(cycle_start, cycle_end)} · "
            f"resets in {util.format_duration(cycle_end - now)}"
        )
        if cycle_limit > 0:
            fraction = min(1.0, cycle / cycle_limit)
            self._set_progress(
                fraction, util.format_percent(cycle / cycle_limit)
            )
            self.quota_detail.set_text(
                f"{util.format_bytes(cycle)} used of {util.format_bytes(cycle_limit)}"
            )
            self.quota_pct.set_text(f"{util.format_bytes(max(0, cycle_limit - cycle))} left")
        elif day_limit > 0:
            fraction = min(1.0, today / day_limit)
            self._set_progress(fraction, util.format_percent(today / day_limit))
            self.quota_detail.set_text(
                f"Daily limit {util.format_bytes(day_limit)} · "
                f"{util.format_bytes(today)} used today"
            )
            self.quota_pct.set_text(
                f"{util.format_bytes(max(0, day_limit - today))} left today"
            )
        else:
            elapsed = (now - cycle_start) / max(1.0, cycle_end - cycle_start)
            self._set_progress(min(1.0, elapsed), None)
            self.quota_detail.set_text(
                f"{util.format_bytes(cycle)} used this cycle · no limit set"
            )
            self.quota_pct.set_text(
                f"{util.format_duration(cycle_end - now)} left"
            )

        self._evaluate_alerts(
            now=now,
            cycle=cycle,
            cycle_limit=cycle_limit,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            today=today,
            day_limit=day_limit,
            warn=warn,
        )

    def _set_progress(self, fraction: float, text: str | None) -> None:
        self.quota_bar.set_fraction(max(0.0, min(1.0, fraction)))
        self.quota_bar.set_text(text or "")
        for css in ("dw-progress-warn", "dw-progress-error"):
            self.quota_bar.remove_css_class(css)
        if fraction >= 1.0:
            self.quota_bar.add_css_class("dw-progress-error")
        elif fraction >= 0.9:
            self.quota_bar.add_css_class("dw-progress-warn")

    # =====================================================================
    # quota alerts
    # =====================================================================
    def _evaluate_alerts(self, **kw) -> None:
        now = kw["now"]
        alerts: list[tuple[int, str, str, str]] = []
        # (severity, message, notification id, notification body)

        cycle_limit, cycle = kw["cycle_limit"], kw["cycle"]
        day_limit, today = kw["day_limit"], kw["today"]
        warn = kw["warn"]

        if cycle_limit > 0:
            key = quota.cycle_index(now, self.config.cycle_day)
            fraction = cycle / cycle_limit
            if fraction >= 1.0:
                alerts.append((
                    4,
                    f"Monthly limit reached: {util.format_bytes(cycle)} of "
                    f"{util.format_bytes(cycle_limit)} used",
                    f"cycle-exceeded:{key}",
                    "Your billing cycle allowance is used up. Resets in "
                    f"{util.format_duration(kw['cycle_end'] - now)}.",
                ))
            elif fraction >= warn:
                alerts.append((
                    2,
                    f"Monthly limit at {util.format_percent(fraction, 0)}: "
                    f"{util.format_bytes(max(0, cycle_limit - cycle))} left",
                    f"cycle-warn:{key}",
                    f"You have used {util.format_bytes(cycle)} of "
                    f"{util.format_bytes(cycle_limit)} this cycle.",
                ))

        if day_limit > 0:
            key = util.day_key(now)
            fraction = today / day_limit
            if fraction >= 1.0:
                alerts.append((
                    3,
                    f"Daily limit reached: {util.format_bytes(today)} of "
                    f"{util.format_bytes(day_limit)} used today",
                    f"day-exceeded:{key}",
                    "No data left in today's allowance. It resets at midnight.",
                ))
            elif fraction >= warn:
                alerts.append((
                    1,
                    f"Daily limit at {util.format_percent(fraction, 0)}: "
                    f"{util.format_bytes(max(0, day_limit - today))} left",
                    f"day-warn:{key}",
                    f"You have used {util.format_bytes(today)} of "
                    f"{util.format_bytes(day_limit)} today.",
                ))

        if not alerts:
            self.banner.set_revealed(False)
            return

        alerts.sort(key=lambda item: item[0], reverse=True)
        severity, message, notify_id, body = alerts[0]
        self.banner.set_title(message)
        self.banner.set_revealed(True)

        marker = f"notified:{notify_id}"
        if self.config.notify and self.storage.state_get(marker) is None:
            self._send_notification(
                notify_id,
                "Data limit warning" if severity < 3 else "Data limit reached",
                body,
                Gio.NotificationPriority.URGENT
                if severity >= 3
                else Gio.NotificationPriority.NORMAL,
            )
            self.storage.state_set(marker, util.day_key(time.time()))

    def _send_notification(self, nid: str, title: str, body: str, priority=None) -> None:
        app = self.get_application()
        if app is None:
            return
        note = Gio.Notification.new(title)
        note.set_body(body)
        if priority is not None:
            note.set_priority(priority)
        note.add_button("Open Datawatch", "app.activate")
        try:
            app.send_notification(nid, note)
        except Exception:  # pragma: no cover - no notification daemon
            pass

    # =====================================================================
    # history page
    # =====================================================================
    def _on_range_changed(self, drop, _pspec) -> None:
        selected = drop.get_selected()
        if selected != Gtk.INVALID_LIST_POSITION:
            self._history_range = int(selected)
        self._refresh_history()

    def _refresh_history(self) -> None:
        now = time.time()
        tracked = self.sampler.tracked
        selected = self.range_drop.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            selection = self._history_range
        else:
            selection = int(selected)
            self._history_range = selection

        if selection == 0:
            start = util.start_of_day(util.add_days(now, -6))
            span_days = 7
        elif selection == 1:
            start = util.start_of_day(util.add_days(now, -29))
            span_days = 30
        elif selection == 2:
            start, _ = quota.cycle_bounds(now, self.config.cycle_day)
            span_days = max(1, int((now - start) // 86400) + 1)
        else:
            t = time.localtime(now)
            start = util.start_of_day(
                time.mktime((t.tm_year, 1, 1, 12, 0, 0, 0, 0, -1))
            )
            span_days = max(1, int((now - start) // 86400) + 1)

        series = self.storage.daily_series(start, int(now) + 1, tracked)
        day_limit = self.config.day_limit_bytes()
        warn = self.config.warn_percent / 100.0
        today_start = util.start_of_day(now)

        items = []
        for day, rx, tx in series:
            total = rx + tx
            tone = "ok"
            if day_limit > 0:
                ratio = total / day_limit
                tone = "error" if ratio >= 1 else ("warn" if ratio >= warn else "ok")
            if day == today_start and tone == "ok":
                tone = "active"
            label_fmt = "%d" if span_days <= 31 else "%b %d"
            items.append((util.format_date(day, label_fmt), total, tone))
        self.bars.set_items(items)

        down = sum(rx for _, rx, _ in series)
        up = sum(tx for _, _, tx in series)
        label = HISTORY_RANGES[selection].lower()
        self.history_total.set_text(
            f"{label}: ↓ {util.format_bytes(down)}   ↑ {util.format_bytes(up)}"
            f"   ·   {util.format_bytes(down + up)} total"
        )

        # rows (newest first)
        child = self.history_rows.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.history_rows.remove(child)
            child = nxt

        for day, rx, tx in reversed(series):
            total = rx + tx
            tone = None
            if day_limit > 0:
                ratio = total / day_limit
                tone = "dw-error" if ratio >= 1 else ("dw-warn" if ratio >= warn else None)
            if day == today_start and tone is None:
                tone = "dw-up"
            row = _table_row(
                (
                    util.format_date(day, "%a, %b %d"),
                    util.format_bytes(rx),
                    util.format_bytes(tx),
                    util.format_bytes(total),
                ),
                tones=(None, None, None, tone),
            )
            self.history_rows.append(row)

        has_rows = len(series) > 0
        self.history_table.set_visible(has_rows)
        self.history_empty.set_visible(not has_rows)

    # =====================================================================
    # interfaces page
    # =====================================================================
    def _refresh_interfaces(self) -> None:
        names = netstat.interface_names(include_loopback=True)
        names = sorted(set(names) | set(self.config.interfaces))
        tracked = set(self.sampler.tracked)
        lifetime = self.storage.all_time_per_interface()
        now = time.time()
        day_start, day_end = quota.day_bounds(now)
        cycle_start, _ = quota.cycle_bounds(now, self.config.cycle_day)
        cycle_end_ts = int(now) + 1

        # drop vanished adapters
        for name in [n for n in self._iface_rows if n not in names]:
            self.iface_rows_box.remove(self._iface_rows.pop(name)["row"])

        for name in names:
            if name not in self._iface_rows:
                self._iface_rows[name] = self._create_interface_row(name)
            self._update_interface_row(
                name, tracked, lifetime, day_start, day_end, cycle_start, cycle_end_ts
            )

    def _create_interface_row(self, name: str) -> dict:
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
                        margin_start=10, margin_end=10,
                        margin_top=8, margin_bottom=8)
        outer.set_hexpand(True)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_hexpand(True)
        name_label = _label(name, css="heading")
        info_label = _label("", css="dw-caption")

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        right.set_valign(Gtk.Align.CENTER)
        rate_label = _label("↓ –  ↑ –", css="dw-cell", xalign=1)
        rate_label.set_size_request(COLUMN_WIDTH, -1)
        totals_label = _label("", css="dw-caption", xalign=1)
        totals_label.set_size_request(COLUMN_WIDTH, -1)

        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.connect("notify::active", self._on_interface_switch, name)

        left.append(name_label)
        left.append(info_label)
        right.append(rate_label)
        right.append(totals_label)
        outer.append(left)
        outer.append(right)
        outer.append(switch)
        self.iface_rows_box.append(outer)

        return {
            "row": outer,
            "name": name_label,
            "info": info_label,
            "rate": rate_label,
            "totals": totals_label,
            "switch": switch,
        }

    def _update_interface_row(
        self, name, tracked, lifetime, day_start, day_end, cycle_start, cycle_end
    ) -> None:
        parts = self._iface_rows[name]
        info = netstat.describe(name)
        is_tracked = name in tracked
        state = "connected" if info["up"] else "disconnected"
        speed = f" · {info['speed']} Mb/s" if info["speed"] else ""
        parts["info"].set_text(f"{info['kind']} · {state}{speed}"
                              f"{'' if is_tracked else ' · not counted'}")
        parts["name"].set_text(name)

        day_rx, day_tx = self.storage.totals(day_start, day_end, [name])
        cyc_rx, cyc_tx = self.storage.totals(cycle_start, cycle_end, [name])
        life = lifetime.get(name, (0, 0))
        parts["totals"].set_text(
            f"today {util.format_bytes(day_rx + day_tx)} · "
            f"cycle {util.format_bytes(cyc_rx + cyc_tx)} · "
            f"all {util.format_bytes(life[0] + life[1])}"
        )

        rate = self.sampler.rates.get(name, (0.0, 0.0))
        parts["rate"].set_text(
            f"↓ {util.format_rate(rate[0])}   ↑ {util.format_rate(rate[1])}"
        )

        self._updating_switches = True
        parts["switch"].set_active(is_tracked)
        self._updating_switches = False

    def _update_interface_rates(self) -> None:
        for name, parts in self._iface_rows.items():
            rate = self.sampler.rates.get(name, (0.0, 0.0))
            parts["rate"].set_text(
                f"↓ {util.format_rate(rate[0])}   ↑ {util.format_rate(rate[1])}"
            )

    def _on_interface_switch(self, switch, _pspec, name: str) -> None:
        if self._updating_switches:
            return
        selected = set(self.sampler.tracked)
        if switch.get_active():
            selected.add(name)
        else:
            selected.discard(name)
        ordered = sorted(selected)
        automatic = netstat.interface_names(
            include_loopback=not self.config.exclude_loopback
        )
        self.config.interfaces = [] if sorted(automatic) == ordered else ordered
        self.config.save()
        self._refresh_totals()
        self._refresh_interfaces()

    # =====================================================================
    # pages / settings / lifecycle
    # =====================================================================
    def _on_page_changed(self, *_args) -> None:
        name = self.stack.get_visible_child_name()
        if name == "history":
            self._refresh_history()
        elif name == "apps":
            self.apps_page.refresh()
        elif name == "interfaces":
            self._refresh_interfaces()

    def _tracked(self) -> list[str]:
        return self.sampler.tracked

    def open_settings(self) -> None:
        if self._settings is not None:
            self._settings.present()
            return
        dialog = SettingsWindow(
            self.get_application(),
            self.config,
            self._tracked,
            self._on_settings_saved,
        )
        dialog.set_transient_for(self)
        dialog.connect(
            "close-request",
            lambda *_: self._forget_settings(),
        )
        self._settings = dialog
        dialog.present()

    def _forget_settings(self, *_args) -> bool:
        self._settings = None
        return False

    def _on_settings_saved(self, values: dict) -> None:
        changed_poll = abs(values["poll_interval"] - self.config.poll_interval) > 1e-6
        changed_window = values["graph_window"] != self.config.graph_window
        changed_scheme = values["color_scheme"] != self.config.color_scheme

        for key, value in values.items():
            setattr(self.config, key, value)
        self.config.save()

        if changed_scheme:
            theme.apply_color_scheme(self.config.color_scheme)
        self.storage.prune(time.time() - self.config.retention_days * 86400)
        self.storage.clear_notified()
        self.sampler.tracker.reconfigure(self.config.track_apps)

        if changed_poll or changed_window:
            self.sampler.restart()
        self.graph.set_capacity(
            int(self.config.graph_window / max(1.0, self.config.poll_interval))
        )
        self.graph_hint.set_text(
            f"last {util.format_duration(self.config.graph_window)}"
        )

        self._enforce()  # new limits / actions apply immediately
        self._refresh_totals()
        self._refresh_interfaces()
        self._refresh_history()
        self.apps_page.refresh()
        self.toast_overlay.add_toast(Adw.Toast(title="Preferences saved", timeout=3))

    def _on_close_request(self, *_args) -> bool:
        if self.config.background_on_close:
            self.hide()
            if not self._background_hinted:
                self._background_hinted = True
                self._send_notification(
                    "background",
                    f"{APP_NAME} is still monitoring",
                    "Usage keeps being recorded in the background. "
                    "Run “datawatch” again to reopen the dashboard.",
                )
            return True
        app = self.get_application()
        if app is not None:
            app.quit()
        return True

    def shutdown(self) -> None:
        self.sampler.stop()
