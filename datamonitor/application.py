"""The Gtk/Adw application object: single instance, actions, startup."""

from __future__ import annotations

import signal

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, __version__  # noqa: E402
from . import theme  # noqa: E402
from .config import Config  # noqa: E402
from .enforce import Enforcer  # noqa: E402
from .sampler import Sampler  # noqa: E402
from .storage import Storage  # noqa: E402
from .window import MainWindow  # noqa: E402


class DataMonitorApp(Adw.Application):
    def __init__(
        self,
        start_hidden: bool = False,
        start_page: str | None = None,
        open_settings: bool = False,
    ):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.start_hidden = start_hidden
        self.start_page = start_page
        self.open_settings_on_start = open_settings
        self.config = Config.load()
        self.storage = Storage()
        self.sampler = Sampler(self.storage, self.config, on_tick=self._dispatch_tick)
        self.enforcer = Enforcer(self.config, self.storage, notify=self._notify_enforcement)
        self.window: MainWindow | None = None

        self._install_actions()
        self.set_accels_for_action("app.preferences", ["<Control>comma"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    # -- actions ----------------------------------------------------------
    def _install_actions(self) -> None:
        handlers = {
            "activate": lambda *_: self.activate_window(),
            "preferences": lambda *_: self.show_preferences(),
            "about": lambda *_: self.show_about(),
            "quit": lambda *_: self.quit(),
        }
        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def activate_window(self) -> None:
        if self.window is None:
            self.window = MainWindow(
                self, self.config, self.storage, self.sampler, self.enforcer
            )
            if self.start_page:
                self.window.stack.set_visible_child_name(self.start_page)
            if self.open_settings_on_start:
                self.window.open_settings()
            if self.start_hidden:
                self.start_hidden = False
                self._notify_background()
            else:
                self.window.present()
        else:
            if self.start_page:
                self.window.stack.set_visible_child_name(self.start_page)
            self.window.set_visible(True)
            self.window.present()

    def show_preferences(self) -> None:
        self.activate_window()
        if self.window is not None:
            self.window.open_settings()

    def show_about(self) -> None:
        self.activate_window()
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name=APP_NAME,
            application_icon="datamonitor",
            developer_name="Patrick",
            version=__version__,
            comments=(
                "Monitors internet data usage per network interface using the "
                "kernel's own counters - no root, no packet capture.\n"
                "History is stored locally in SQLite."
            ),
            license_type=Gtk.License.MIT,
            developers=["Patrick"],
            copyright="© 2026",
        )
        about.present()

    def _notify_background(self) -> None:
        note = Gio.Notification.new(f"{APP_NAME} is running in the background")
        note.set_body("The dashboard is hidden but usage keeps being recorded. "
                      "Run “datamonitor” again to open it.")
        note.add_button("Open dashboard", "app.activate")
        try:
            self.send_notification("background", note)
        except Exception:  # pragma: no cover
            pass

    def _notify_enforcement(self, nid: str, title: str, body: str, urgent: bool = False) -> None:
        """Desktop notification from the limit enforcer (pause events)."""
        note = Gio.Notification.new(title)
        note.set_body(body)
        if urgent:
            note.set_priority(Gio.NotificationPriority.URGENT)
        note.add_button("Open Data Monitor", "app.activate")
        try:
            self.send_notification(nid, note)
        except Exception:  # pragma: no cover - no notification daemon
            pass

    # -- runtime ----------------------------------------------------------
    def _dispatch_tick(self, sampler) -> None:
        if self.window is not None:
            self.window.on_sample(sampler)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        theme.install_css()
        theme.apply_color_scheme(self.config.color_scheme)
        for signum in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, self._on_unix_signal)
        # Drop anything older than the retention window before showing numbers.
        try:
            self.storage.prune(
                GLib.get_real_time() // 1_000_000 - self.config.retention_days * 86400
            )
        except Exception:  # pragma: no cover - never block startup on maintenance
            pass

    def do_activate(self) -> None:
        self.activate_window()

    def do_shutdown(self) -> None:
        try:
            # Never leave apps frozen when Data Monitor exits.
            self.enforcer.shutdown()
        except Exception:  # pragma: no cover
            pass
        try:
            self.sampler.stop()
        finally:
            try:
                self.storage.close()
            except Exception:  # pragma: no cover
                pass
        Adw.Application.do_shutdown(self)

    def _on_unix_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE


def run(argv: list[str] | None = None) -> int:
    """Convenience entry point (``datamonitor.application.run()``)."""
    app = DataMonitorApp()
    return app.run(argv)
