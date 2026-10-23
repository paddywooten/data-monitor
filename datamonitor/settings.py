"""The preferences window (limits, tracked interfaces, behaviour)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from . import netstat, sysproc  # noqa: E402

RANGE_CHOICES = (
    "Last 7 days",
    "Last 30 days",
    "This billing cycle",
    "This year",
)

_COLOR_CHOICES = ("Follow system", "Light", "Dark")
_COLOR_VALUES = ("system", "light", "dark")

_ACTION_CHOICES = ("Notify me", "Pause the app(s)")
_ACTION_VALUES = ("notify", "pause")


def _spin_row(
    title: str,
    subtitle: str,
    lower: float,
    upper: float,
    value: float,
    digits: int = 0,
    suffix: str | None = None,
) -> Adw.SpinRow:
    adjustment = Gtk.Adjustment(
        lower=lower,
        upper=upper,
        step_increment=1,
        page_increment=10,
        value=value,
    )
    row = Adw.SpinRow(
        title=title,
        subtitle=subtitle,
        adjustment=adjustment,
        digits=digits,
        numeric=True,
        snap_to_ticks=True,
        climb_rate=0.5,
        valign=Gtk.Align.CENTER,
    )
    if suffix:
        label = Gtk.Label(label=suffix, xalign=1, valign=Gtk.Align.CENTER)
        label.add_css_class("dw-caption")
        row.add_suffix(label)
    row.set_activatable(False)
    return row


def _switch_row(title: str, subtitle: str, active: bool) -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title, subtitle=subtitle, active=active)
    return row


class SettingsWindow(Adw.Window):
    """Modal preferences dialog; hands a plain dict back to the caller."""

    def __init__(self, app, config, tracked_provider, on_save):
        super().__init__(
            application=app,
            title="Preferences",
            modal=True,
            default_width=560,
            default_height=680,
        )
        self.config = config
        self.tracked_provider = tracked_provider
        self.on_save = on_save
        self._iface_rows: dict[str, Adw.SwitchRow] = {}
        self._selected: set[str] = set(tracked_provider())
        self._manual = bool(config.interfaces)

        self.set_resizable(True)
        self._build()

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Preferences", css_classes=["heading"]))

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        save = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save.connect("clicked", self._on_save)
        header.add_css_class("headerbar")
        header.pack_end(save)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.add(self._limits_group())
        page.add(self._interfaces_group())
        page.add(self._monitoring_group())
        page.add(self._behaviour_group())
        toolbar.set_content(page)

        self.set_content(toolbar)

    def _limits_group(self) -> Adw.PreferencesGroup:
        cfg = self.config
        group = Adw.PreferencesGroup(
            title="Data limits",
            description="Limits are checked against everything that is tracked. "
            "Set a value to 0 to disable that limit.",
        )
        self.row_cycle_limit = _spin_row(
            "Billing cycle limit",
            "Allowance per billing cycle",
            0,
            100_000,
            cfg.cycle_limit_gb,
            digits=1,
            suffix="GB",
        )
        self.row_day_limit = _spin_row(
            "Daily limit",
            "Allowance per calendar day",
            0,
            100_000,
            cfg.day_limit_gb,
            digits=1,
            suffix="GB",
        )
        self.row_warn = _spin_row(
            "Warn me at",
            "Percentage of a limit reached before warning",
            10,
            100,
            cfg.warn_percent,
            digits=0,
            suffix="%",
        )
        self.row_cycle_day = _spin_row(
            "Billing cycle starts on",
            "Day of the month the cycle resets",
            1,
            28,
            cfg.cycle_day,
            digits=0,
            suffix="of month",
        )
        for row in (
            self.row_cycle_limit,
            self.row_day_limit,
            self.row_warn,
            self.row_cycle_day,
        ):
            group.add(row)
        return group

    def _interfaces_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Tracked interfaces",
            description=self._interfaces_description(),
        )
        refresh = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Rescan interfaces",
            valign=Gtk.Align.CENTER,
        )
        refresh.connect("clicked", lambda *_: self._sync_interfaces())
        group.set_header_suffix(refresh)
        self._iface_group = group
        self._iface_description = Gtk.Label(
            label=self._interfaces_description(), xalign=0, wrap=True
        )
        self._sync_interfaces()
        return group

    def _interfaces_description(self) -> str:
        if self._manual:
            return "Only the interfaces switched on are counted toward your limits."
        return (
            "Automatic: every interface except loopback is counted. "
            "Toggling a switch switches to a manual selection."
        )

    def _sync_interfaces(self) -> None:
        """Add / remove interface switches so the list matches the system."""
        names = netstat.interface_names(include_loopback=True)
        if "lo" in names:
            names.remove("lo")
            names.append("lo")

        for name in [n for n in self._iface_rows if n not in names]:
            self._iface_group.remove(self._iface_rows.pop(name))

        for name in names:
            if name in self._iface_rows:
                continue
            info = netstat.describe(name)
            row = _switch_row(
                name,
                f"{info['kind']} · {'connected' if info['up'] else 'disconnected'}",
                name in self._selected,
            )
            row.connect("notify::active", self._on_iface_toggle, name)
            self._iface_rows[name] = row
            self._iface_group.add(row)

        description = self._interfaces_description()
        self._iface_group.set_description(description)

    def _on_iface_toggle(self, row, _pspec, name: str) -> None:
        self._manual = True
        if row.get_active():
            self._selected.add(name)
        else:
            self._selected.discard(name)
        self._iface_group.set_description(self._interfaces_description())

    def _monitoring_group(self) -> Adw.PreferencesGroup:
        cfg = self.config
        group = Adw.PreferencesGroup(
            title="Monitoring",
            description="How the samples are collected and stored.",
        )
        self.row_poll = _spin_row(
            "Sampling interval",
            "How often the kernel counters are read",
            1,
            60,
            cfg.poll_interval,
            digits=0,
            suffix="seconds",
        )
        self.row_window = _spin_row(
            "Graph window",
            "Amount of live history shown on the dashboard",
            30,
            3600,
            cfg.graph_window,
            digits=0,
            suffix="seconds",
        )
        self.row_retention = _spin_row(
            "History retention",
            "Older samples are deleted automatically",
            7,
            36500,
            cfg.retention_days,
            digits=0,
            suffix="days",
        )
        self.row_track_apps = _switch_row(
            "Track per-app usage",
            "Attribute traffic to programs (TCP only, needs ss)",
            cfg.track_apps,
        )
        for row in (
            self.row_poll,
            self.row_window,
            self.row_retention,
        ):
            group.add(row)
        if sysproc.IS_LINUX:
            # Byte attribution (ss) is Linux-only; the row is still built so
            # the saved value round-trips untouched on other platforms.
            group.add(self.row_track_apps)
        return group

    def _behaviour_group(self) -> Adw.PreferencesGroup:
        cfg = self.config
        group = Adw.PreferencesGroup(title="Behaviour")
        self.row_notify = _switch_row(
            "Desktop notifications",
            "Warn when a limit is close or reached",
            cfg.notify,
        )
        self.row_background = _switch_row(
            "Keep running when closed",
            "Close the window but keep recording usage",
            cfg.background_on_close,
        )
        group.add(self.row_notify)
        group.add(self.row_background)

        self.row_overall_action = Adw.ComboRow(
            title="When my overall limit is hit",
            subtitle="Daily or billing-cycle cap reached",
            model=Gtk.StringList.new(list(_ACTION_CHOICES)),
            selected=_ACTION_VALUES.index(cfg.overall_action),
        )
        group.add(self.row_overall_action)

        self.row_app_action = Adw.ComboRow(
            title="When an app's own limit is hit",
            subtitle="Per-app limits from the Apps tab",
            model=Gtk.StringList.new(list(_ACTION_CHOICES)),
            selected=_ACTION_VALUES.index(cfg.app_action),
        )
        if sysproc.IS_LINUX:
            # Per-app limits need byte attribution, which is Linux-only.
            group.add(self.row_app_action)

        selected = _COLOR_VALUES.index(cfg.color_scheme)
        self.row_theme = Adw.ComboRow(
            title="Appearance",
            subtitle="Colour scheme of this app",
            model=Gtk.StringList.new(list(_COLOR_CHOICES)),
            selected=selected,
        )
        group.add(self.row_theme)
        return group

    # -- events -----------------------------------------------------------
    def _on_key(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_save(self, *_args) -> None:
        interface_list = sorted(self._selected)
        # Keep "automatic" mode as long as the manual choice still matches it.
        automatic = [
            n for n in netstat.interface_names(include_loopback=False)
        ]
        if self._manual and sorted(automatic) == interface_list:
            interface_list = []

        theme_value = _COLOR_VALUES[self.row_theme.get_selected()]
        values = {
            "cycle_limit_gb": float(self.row_cycle_limit.get_value()),
            "day_limit_gb": float(self.row_day_limit.get_value()),
            "warn_percent": float(self.row_warn.get_value()),
            "cycle_day": int(self.row_cycle_day.get_value()),
            "interfaces": interface_list,
            "poll_interval": float(self.row_poll.get_value()),
            "graph_window": int(self.row_window.get_value()),
            "retention_days": int(self.row_retention.get_value()),
            "notify": bool(self.row_notify.get_active()),
            "background_on_close": bool(self.row_background.get_active()),
            "color_scheme": theme_value,
            "track_apps": bool(self.row_track_apps.get_active()),
            "overall_action": _ACTION_VALUES[self.row_overall_action.get_selected()],
            "app_action": _ACTION_VALUES[self.row_app_action.get_selected()],
        }
        self.on_save(values)
        self.close()
