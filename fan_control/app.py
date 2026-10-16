"""GTK 4 / libadwaita interface. Run with the system Python for PyGObject."""

import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import __version__
from .authorization import AuthorizationSession
from .hardware import DemoHardware, Hardware, PROFILES
from .host import HostHardware
from .power_profiles import (
    is_live_hardware,
    subscribe_desktop_changes,
    sync_to_desktop,
    unsubscribe_desktop_changes,
)
from .native import FLATPAK_INFO
from .service import install_service_async, is_service_active, uninstall_service_async
from .shortcuts import setup_omen_shortcut


APP_ID = "io.github.sh7vansh.VictusFanControl"
DATA = Path(__file__).resolve().parent.parent / "data"


def restart_app():
    if FLATPAK_INFO.exists():
        cmd = ["/usr/bin/flatpak-spawn", "--host", "flatpak", "run", APP_ID]
        Gio.Subprocess.new(cmd, Gio.SubprocessFlags.NONE)
    else:
        cmd = [sys.executable, "-m", "fan_control"]
        Gio.Subprocess.new(cmd, Gio.SubprocessFlags.NONE)
    app = Gio.Application.get_default()
    if app:
        app.quit()
    else:
        sys.exit(0)


def fan_icon(size=16):
    icon = Gio.FileIcon.new(Gio.File.new_for_path(str(DATA / "icons/hicolor/symbolic/actions/fan-control-symbolic.svg")))
    image = Gtk.Image.new_from_gicon(icon)
    image.set_pixel_size(size)
    return image


class FanCard(Adw.Bin):
    def __init__(self, label):
        super().__init__(hexpand=True)
        self.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=20, margin_bottom=20, margin_start=12, margin_end=12)
        icon = fan_icon(36)
        icon.add_css_class("accent")
        box.append(icon)
        self.name = Gtk.Label(label=label, margin_top=4)
        self.name.add_css_class("heading")
        box.append(self.name)
        value_box = Gtk.Box(spacing=5, halign=Gtk.Align.CENTER)
        self.value = Gtk.Label(label="—")
        self.value.add_css_class("rpm")
        value_box.append(self.value)
        unit = Gtk.Label(label="RPM", valign=Gtk.Align.BASELINE)
        unit.add_css_class("dim-label")
        value_box.append(unit)
        box.append(value_box)
        self.state = Gtk.Label(label="Reading…")
        self.state.add_css_class("caption")
        self.state.add_css_class("dim-label")
        box.append(self.state)
        self.set_child(box)

    def update(self, name, rpm):
        self.name.set_label(name)
        self.value.set_label(f"{rpm:,}" if rpm is not None else "—")
        self.state.set_label("Unavailable" if rpm is None else "Stopped" if rpm == 0 else "Running")
        self.set_tooltip_text(f"{name}: {rpm:,} revolutions per minute" if rpm is not None
                              else f"{name}: no reading available")


class FanWindow(Adw.ApplicationWindow):
    def __init__(self, application, hardware):
        super().__init__(application=application, title="Fan Control",
                         default_width=520, default_height=820)
        self.hardware = hardware
        self.snapshot = hardware.read()
        self.busy = False
        self.syncing = False
        self.error_detail = ""
        self.authorization = None
        if not isinstance(hardware, DemoHardware):
            factory = getattr(application, "authorization_factory", None)
            self.authorization = factory() if factory else AuthorizationSession()
            self.authorization.changed = self.update_authorization
        self.service_action = Gio.SimpleAction.new("manage-service", None)
        self.service_action.connect("activate", self.on_manage_service)
        self.service_action.set_enabled(not isinstance(hardware, DemoHardware))
        self.add_action(self.service_action)
        self.desktop_sync_id = None
        if is_live_hardware(hardware):
            self.desktop_sync_id = subscribe_desktop_changes(self._on_desktop_profile_change)
        self.connect("close-request", self.on_close)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Fan Control", subtitle="HP Victus / OMEN"))
        menu = Gio.Menu()
        menu.append("Background Service…", "win.manage-service")
        menu.append("About Fan Control", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        toolbar.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        self.toast_overlay.set_child(toolbar)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.service_banner = Adw.Banner(title="Background service required for cooling controls",
                                         button_label="Enable Service", revealed=False)
        self.service_banner.connect("button-clicked", lambda *_: self.on_manage_service(None, None))
        outer.append(self.service_banner)
        self.error_banner = Adw.Banner(title="The setting could not be changed", button_label="Details", revealed=False)
        self.error_banner.connect("button-clicked", self.show_error)
        outer.append(self.error_banner)
        self.host_banner = Adw.Banner(title="Cannot read laptop settings", button_label="Details", revealed=False)
        self.host_banner.connect("button-clicked", self.show_host_error)
        outer.append(self.host_banner)
        if isinstance(hardware, DemoHardware):
            outer.append(Adw.Banner(title="Preview mode — hardware settings are not changed", revealed=True))
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        outer.append(scroll)
        clamp = Adw.Clamp(maximum_size=560, tightening_threshold=420)
        scroll.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                       margin_top=12, margin_bottom=20, margin_start=24, margin_end=24)
        clamp.set_child(body)
        toolbar.set_content(outer)

        live = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        fan_box = Gtk.Box(spacing=12, homogeneous=True)
        self.fans = [FanCard("CPU fan"), FanCard("GPU fan")]
        for card in self.fans:
            fan_box.append(card)
        live.append(fan_box)
        self.live_label = Gtk.Label(label="Updated every second")
        self.live_label.add_css_class("dim-label")
        self.live_label.add_css_class("caption")
        live.append(self.live_label)
        body.append(live)

        self.profiles_group = Adw.PreferencesGroup(
            title="Thermal profile", description="Your firmware adjusts cooling and performance together.")
        self.profile_buttons = {}
        self.profile_rows = {}
        first = None
        for profile, (title, subtitle, icon) in PROFILES.items():
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            image = Gtk.Image.new_from_icon_name(icon)
            row.add_prefix(image)
            button = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            button.update_property([Gtk.AccessibleProperty.LABEL], [f"{title} thermal profile"])
            if first is None:
                first = button
            else:
                button.set_group(first)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            button.connect("toggled", self.on_profile, profile)
            self.profiles_group.add(row)
            self.profile_buttons[profile] = button
            self.profile_rows[profile] = row
        body.append(self.profiles_group)

        self.override_group = Adw.PreferencesGroup(title="Fan override")
        self.maximum = Adw.SwitchRow(title="Max fan speed",
                                    subtitle="Run both fans at full speed")
        self.maximum.add_prefix(fan_icon())
        self.maximum.connect("notify::active", self.on_maximum)
        self.override_group.add(self.maximum)
        body.append(self.override_group)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner()
        status_box.append(self.spinner)
        self.status = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.status.add_css_class("heading")
        status_box.append(self.status)
        footer.append(status_box)
        self.help_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.help_label.add_css_class("dim-label")
        self.help_label.add_css_class("caption")
        footer.append(self.help_label)
        self.auth = Gtk.Label(wrap=True,
                         justify=Gtk.Justification.CENTER, margin_top=4)
        self.auth.add_css_class("dim-label")
        self.auth.add_css_class("caption")
        footer.append(self.auth)
        self.update_authorization()
        body.append(footer)
        self.refresh()
        self.poll_source = GLib.timeout_add_seconds(1, self.refresh)

    def refresh(self, poll=True):
        if isinstance(self.hardware, HostHardware) and poll:
            self.hardware.poll(lambda: self.refresh(False))
        self.snapshot = self.hardware.read()
        s = self.snapshot
        for card, name, rpm in zip(self.fans, s.labels, s.rpm):
            card.update(name, rpm)
        self.live_label.set_label("Updated every second" if all(x is not None for x in s.rpm)
                                  else "Some fan readings are unavailable" if any(x is not None for x in s.rpm)
                                  else "Fan readings unavailable — HP controller not found or unreadable")
        if self.busy:
            return GLib.SOURCE_CONTINUE
        self.syncing = True
        try:
            for profile, button in self.profile_buttons.items():
                button.set_active(profile == s.profile)
                available = profile in s.choices and s.profile is not None
                self.profile_rows[profile].set_sensitive(available)
                self.profile_rows[profile].set_tooltip_text(None if available else "Not exposed by your firmware")
            self.maximum.set_sensitive(s.mode is not None)
            self.maximum.set_active(s.mode == 0)
        finally:
            self.syncing = False
        if s.profile is None:
            self.profiles_group.set_description("Thermal profiles are unavailable on this system.")
        else:
            title = PROFILES.get(s.profile, (s.profile.replace("-", " ").capitalize(),))[0]
            self.profiles_group.set_description(f"Current profile: {title}")
        if s.mode == 0:
            self.status.set_label("Maximum cooling")
            self.help_label.set_label("Turn off Max fan speed to return to automatic control.\nThis setting stays active when you close the app.")
            self.override_group.set_description("Max fan speed overrides the profile’s automatic fan curve.")
        elif s.mode == 2:
            self.status.set_label("Automatic cooling")
            self.help_label.set_label("The firmware controls fan speed.\nAt 0 RPM, a fan is stopped; this can be normal when the laptop is cool.")
            self.override_group.set_description(None)
        elif s.mode is not None:
            self.status.set_label(f"Fan control mode {s.mode}")
            self.help_label.set_label("Another tool may be controlling the fans.\nToggle Max fan speed on, then off, to return to automatic control.")
            self.override_group.set_description("The controller is in another fan control mode.")
        else:
            self.status.set_label("Fan override unavailable")
            self.help_label.set_label("The HP fan controller is missing or unreadable.\nThermal profiles can still be used when available.")
            self.override_group.set_description("Requires an HP controller provided by the hp-wmi kernel driver.")
        if isinstance(self.hardware, HostHardware):
            self.host_banner.set_revealed(self.hardware.error is not None)
            if not self.hardware.available:
                self.status.set_label("Reading laptop settings…" if self.hardware.error is None else "Host access unavailable")
                self.help_label.set_label("Allow this app to run host commands in its Flatpak permissions.")
        return GLib.SOURCE_CONTINUE

    def on_profile(self, button, profile):
        if self.syncing or self.busy or not button.get_active() or self.snapshot.profile == profile:
            return
        try:
            request = self.hardware.profile_request(profile)
        except ValueError as error:
            self.fail(str(error))
            return
        self.begin_write(request, f"{PROFILES[profile][0]} profile applied")

    def on_maximum(self, row, _param):
        if self.syncing or self.busy or row.get_active() == (self.snapshot.mode == 0):
            return
        try:
            request = self.hardware.fan_request(row.get_active())
        except ValueError as error:
            self.fail(str(error))
            return
        self.begin_write(request, "Max fan speed enabled" if row.get_active() else "Automatic fan control restored")

    def begin_write(self, request, success_message):
        # Revert the widget to the hardware state until authorization/write succeeds.
        self.refresh()
        self.busy = True
        self.update_authorization()
        self.error_banner.set_revealed(False)
        for row in self.profile_rows.values():
            row.set_sensitive(False)
        self.maximum.set_sensitive(False)
        self.spinner.set_spinning(True)
        self.status.set_label("Applying setting…" if self.authorization is None or self.authorization.unlocked else "Connecting to background service…")
        if isinstance(self.hardware, DemoHardware):
            def apply_demo():
                self.hardware.apply(request)
                self.complete_write(request, success_message)
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(180, apply_demo)
            return
        def written(error):
            if error is not None:
                self.fail(str(error))
            else:
                GLib.timeout_add(250, self.complete_write, request, success_message)
        self.authorization.change(request, written)

    def update_authorization(self):
        unlocked = self.authorization is not None and self.authorization.unlocked
        active = False if isinstance(self.hardware, DemoHardware) else is_service_active()
        if hasattr(self, "service_banner"):
            self.service_banner.set_revealed(not active and not isinstance(self.hardware, DemoHardware))
        if hasattr(self, "auth"):
            if self.authorization is None:
                self.auth.set_label("Preview mode does not require background service.")
            elif unlocked:
                self.auth.set_label("Background service active (passwordless).")
            elif active:
                self.auth.set_label("Background service active. Restart app to connect.")
            else:
                self.auth.set_label("Background service is not running.")
        if unlocked and self.busy:
            self.status.set_label("Applying setting…")

    def on_manage_service(self, _action, _param):
        active = is_service_active()
        socket_visible = self.authorization and self.authorization.socket_path and self.authorization.socket_path.exists()
        if active and not socket_visible and FLATPAK_INFO.exists():
            status_text = "Active on host (restart app to activate passwordless control)"
        elif active:
            status_text = "Active (passwordless control enabled)"
        else:
            status_text = "Inactive"
        dialog = Adw.AlertDialog.new(
            "Background Service",
            f"Enable the system service to change cooling settings without repeated authentication. Only your user account and root can connect. Update Service refreshes the installed helper after an app update.\n\nStatus: {status_text}"
        )
        dialog.add_response("cancel", "Cancel")
        if active:
            dialog.add_response("install", "Update Service")
            dialog.add_response("uninstall", "Disable Service")
            dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dialog.add_response("install", "Enable Service")
            dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response == "install":
                self.toast_overlay.add_toast(Adw.Toast(title="Configuring background service…"))
                install_service_async(self._on_service_installed)
            elif response == "uninstall":
                self.toast_overlay.add_toast(Adw.Toast(title="Removing background service…"))
                uninstall_service_async(self._on_service_uninstalled)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_service_installed(self, error):
        if error is not None:
            self.fail(f"Failed to configure background service: {error}")
            return
        if self.authorization:
            self.authorization.close()
            if not FLATPAK_INFO.exists():
                self.authorization.connect()
        self.update_authorization()
        # Flatpak may still bind the previous socket inode after a service restart.
        if FLATPAK_INFO.exists():
            dialog = Adw.AlertDialog.new(
                "Restart Required",
                "The background service is now installed and active on your system.\n\nRestart the application to connect to its new socket."
            )
            dialog.add_response("later", "Restart Later")
            dialog.add_response("restart", "Restart Now")
            dialog.set_response_appearance("restart", Adw.ResponseAppearance.SUGGESTED)

            def on_response(_d, response):
                if response == "restart":
                    restart_app()

            dialog.connect("response", on_response)
            dialog.present(self)
        else:
            self.toast_overlay.add_toast(Adw.Toast(title="Background service enabled"))

    def _on_service_uninstalled(self, error):
        if error is not None:
            self.fail(f"Failed to remove background service: {error}")
            return
        self.toast_overlay.add_toast(Adw.Toast(title="Background service disabled"))
        if self.authorization:
            self.authorization.close()
        self.update_authorization()

    def complete_write(self, request, message):
        if isinstance(self.hardware, HostHardware):
            def verified(error):
                if error is not None:
                    self.fail(str(error))
                    return
                self.busy = False
                self.update_authorization()
                self.spinner.set_spinning(False)
                self.refresh()
                self.toast_overlay.add_toast(Adw.Toast(title=message))
                if is_live_hardware(self.hardware) and request.path.name == "platform_profile":
                    sync_to_desktop(request.value)
            self.hardware.verify_async(request, verified)
            return GLib.SOURCE_REMOVE
        try:
            self.hardware.verify(request)
            self.busy = False
            self.update_authorization()
            self.spinner.set_spinning(False)
            self.refresh()
            self.toast_overlay.add_toast(Adw.Toast(title=message))
            if is_live_hardware(self.hardware) and request.path.name == "platform_profile":
                sync_to_desktop(request.value)
        except ValueError as error:
            self.fail(str(error))
        return GLib.SOURCE_REMOVE

    def _on_desktop_profile_change(self, _firmware_profile):
        GLib.timeout_add(150, self.refresh)

    def fail(self, detail):
        self.busy = False
        self.update_authorization()
        self.spinner.set_spinning(False)
        self.error_detail = detail
        self.error_banner.set_revealed(True)
        self.refresh()

    def show_error(self, _banner):
        dialog = Adw.AlertDialog(heading="Could not apply setting", body=self.error_detail)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.present(self)

    def show_host_error(self, _banner):
        detail = self.hardware.error or "Host access is still connecting."
        dialog = Adw.AlertDialog(heading="Host access unavailable",
                                 body="Allow this app to run host commands in Flatpak permissions. The host also needs polkit and a graphical authentication agent.\n\n" + detail)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.present(self)

    def on_close(self, _window):
        if self.busy:
            self.toast_overlay.add_toast(Adw.Toast(title="Finish or cancel authentication before closing"))
            return True
        GLib.source_remove(self.poll_source)
        if self.desktop_sync_id is not None:
            unsubscribe_desktop_changes(self.desktop_sync_id)
            self.desktop_sync_id = None
        if self.authorization is not None:
            self.authorization.close()
        return False


class FanApplication(Adw.Application):
    def __init__(self, demo=False, smoke_test=False, screenshot=None):
        super().__init__(application_id=APP_ID + (".Preview" if demo else ""),
                         flags=Gio.ApplicationFlags.NON_UNIQUE if smoke_test else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.hardware = (DemoHardware() if demo else HostHardware()
                         if Path("/.flatpak-info").exists() else Hardware())
        self.smoke_test = smoke_test
        self.screenshot = screenshot
        self.failure = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        if FLATPAK_INFO.exists() and not self.smoke_test and not isinstance(self.hardware, DemoHardware):
            setup_omen_shortcut()
        provider = Gtk.CssProvider()
        provider.load_from_string(".rpm { font-size: 34px; font-weight: 700; font-feature-settings: 'tnum'; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.set_search_path([str(DATA / "icons"), *theme.get_search_path()])
        Gtk.Window.set_default_icon_name(APP_ID)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self.show_about)
        self.add_action(about)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.get_active_window().close())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            window = FanWindow(self, self.hardware)
            if self.screenshot:
                self.capture_paintable = Gtk.WidgetPaintable.new(window)
            if self.smoke_test:
                GLib.timeout_add(600, self.run_smoke_step, window, 0)
        window.present()

    def run_smoke_step(self, window, step):
        try:
            if step == 0:
                assert Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon(APP_ID), "Application icon is unavailable"
                assert window.snapshot.profile == "balanced"
                window.profile_buttons["quiet"].set_active(True)
            elif step == 1:
                assert not window.busy and window.snapshot.profile == "quiet"
                window.maximum.set_active(True)
            elif step == 2:
                assert not window.busy and window.snapshot.mode == 0
                assert window.snapshot.rpm == (5200, 4900)
                window.maximum.set_active(False)
            elif step == 3:
                assert not window.busy and window.snapshot.mode == 2
                window.profile_buttons["balanced"].set_active(True)
            else:
                assert not window.busy and window.snapshot.profile == "balanced"
                if step == 4:
                    window.toast_overlay.dismiss_all()
                    GLib.timeout_add(500, self.run_smoke_step, window, 5)
                    return GLib.SOURCE_REMOVE
                if self.screenshot:
                    paintable = self.capture_paintable
                    snapshot = Gtk.Snapshot.new()
                    paintable.snapshot(snapshot, window.get_width(), window.get_height())
                    node = snapshot.to_node()
                    texture = window.get_renderer().render_texture(node, None)
                    assert texture.save_to_png(str(self.screenshot))
                print("GTK smoke test passed: profiles, max fan, automatic mode, and readback", flush=True)
                window.close()
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(500, self.run_smoke_step, window, step + 1)
        except Exception as error:
            print(f"GTK smoke test failed: {error}", file=sys.stderr, flush=True)
            self.failure = True
            self.quit()
        return GLib.SOURCE_REMOVE

    def do_shutdown(self):
        for window in self.get_windows():
            authorization = getattr(window, "authorization", None)
            if authorization is not None:
                authorization.close()
        Adw.Application.do_shutdown(self)

    def show_about(self, *_args):
        dialog = Adw.AboutDialog(application_name="Fan Control", application_icon=APP_ID,
                                 version=__version__, developer_name="Shivansh Singh",
                                 comments="Choose a thermal profile, check both fan speeds, or switch between maximum and automatic cooling on supported HP Victus and OMEN laptops.",
                                 copyright="Copyright © 2026 Shivansh Singh",
                                 license_type=Gtk.License.MIT_X11)
        dialog.set_developers(["Shivansh Singh"])
        metadata = ET.parse(DATA / f"{APP_ID}.metainfo.xml").getroot()
        dialog.set_website(metadata.findtext("url[@type='homepage']"))
        dialog.set_issue_url(metadata.findtext("url[@type='bugtracker']"))
        dialog.add_link("Source Code", metadata.findtext("url[@type='vcs-browser']"))
        release = metadata.find("releases/release")
        if release is not None and release.find("description") is not None:
            notes = "".join(ET.tostring(child, encoding="unicode") for child in release.find("description"))
            dialog.set_release_notes(notes)
            dialog.set_release_notes_version(release.get("version"))
        dialog.set_debug_info(f"Fan Control {__version__}\nGTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}\n"
                              f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}\n"
                              f"Python {sys.version.split()[0]}\nPackaging: {'Flatpak' if Path('/.flatpak-info').exists() else 'Source checkout'}")
        dialog.present(self.get_active_window())


def main():
    parser = argparse.ArgumentParser(description="Native HP Victus / OMEN fan control")
    parser.add_argument("--demo", action="store_true", help="Preview without touching hardware")
    parser.add_argument("--check-host", action="store_true", help="Check Flatpak host access and print live readings without changing settings")
    parser.add_argument("--smoke-test", action="store_true", help="Exercise preview controls and exit")
    parser.add_argument("--screenshot", type=Path, help="Save a preview screenshot during --smoke-test")
    args = parser.parse_args()
    if args.check_host:
        if not Path("/.flatpak-info").exists():
            parser.error("--check-host must be run inside the Flatpak")
        hardware = HostHardware()
        loop = GLib.MainLoop()
        hardware.poll(loop.quit)
        if hardware.pending:
            loop.run()
        if not hardware.available:
            print(hardware.error, file=sys.stderr)
            return 1
        state = hardware.read()
        print(f"Host access OK; profile: {state.profile or 'unavailable'}; fan RPM: {state.rpm[0]}, {state.rpm[1]}")
        return 0
    if args.screenshot and not args.smoke_test:
        parser.error("--screenshot requires --smoke-test")
    app = FanApplication(demo=args.demo or args.smoke_test, smoke_test=args.smoke_test,
                         screenshot=args.screenshot)
    result = app.run([sys.argv[0]])
    return 1 if app.failure else result
