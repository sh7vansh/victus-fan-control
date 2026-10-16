# Fan Control

A native GTK 4 / libadwaita app for HP Victus and OMEN laptops. Select a firmware thermal profile, switch both fans to maximum speed, or return to automatic control. Both fan RPM readings update every second.

<p>
  <img src="data/screenshots/fan-control-light.png" alt="Fan Control in light appearance" width="280">
  <img src="data/screenshots/fan-control-dark.png" alt="Fan Control in dark appearance" width="280">
</p>

## Install

[Download the Flatpak installer](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref) and open it in GNOME Software. Use the `.flatpakref` to see the complete listing and receive updates from the signed repository. Or run:

```sh
flatpak install --user https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref
flatpak run io.github.sh7vansh.VictusFanControl
```

The app uses `flatpak-spawn --host` and the host's `pkexec`; no separate RPM or service is required. **This permits commands outside the sandbox as your user**, which GNOME Software labels “Potentially Unsafe.” Fan changes require administrator authentication once per app session. See [packaging details](packaging/README.md).

Requires supported HP firmware, Python 3.10+, polkit, coreutils, and a graphical authentication agent on the host. The GNOME 51 runtime is supplied by Flathub. Screenshots show live readings from an HP Victus; fan speeds and available controls vary by laptop.

[Project page](https://sh7vansh.github.io/victus-fan-control/) · [Releases](https://github.com/sh7vansh/victus-fan-control/releases) · [Report a problem](https://github.com/sh7vansh/victus-fan-control/issues)

Find **Fan Control** in the GNOME app grid after installation. It follows GNOME's light/dark appearance and accent color. Resize the window to fit; the controls scroll when needed. Ctrl+Q closes the app.

## Run from source for development

On Fedora, use the system Python. Dependencies: `python3-gobject`, `gtk4`, `libadwaita`, and `polkit`. These are already installed on the target laptop. If needed:

```sh
sudo dnf install python3-gobject gtk4 libadwaita polkit
```

From this directory:

```sh
/usr/bin/python3 -m fan_control
```

Source runs use the same temporary session helper directly on the host. Tested with GTK 4.22 and libadwaita 1.9.

## What the controls do

* **Quiet, Cool, Balanced, Performance:** write the selected profile to `/sys/firmware/acpi/platform_profile`. Only profiles reported by `platform_profile_choices` are enabled. These are firmware policies affecting power and thermals together, not custom fan curves or direct RPM targets.
* **Max fan speed on:** writes `0` to the HP controller's `pwm1_enable`.
* **Max fan speed off:** writes `2` to restore firmware automatic fan control.
* **RPM:** reads `fan1_input` and `fan2_input` from the HP controller. Uses firmware labels when exposed, otherwise CPU fan / GPU fan (the HP driver's fan order). Zero is shown as stopped; missing or unreadable readings are shown as unavailable.

The controller is discovered by its `hp` hwmon name and `hp-wmi` platform path, so `hwmon` numbering may change after reboot. The app polls the actual state and reflects changes from GNOME, TuneD, firmware, or other apps. It does not continuously reapply settings or disable the system's power manager. If a setting is immediately overridden, readback reports that it did not stay applied. GNOME power modes and firmware thermal profiles are separate interfaces; their mapping depends on the power manager.

**Settings remain in firmware when the window closes.** To end a max fan burst, turn off Max fan speed before closing. Closing or reopening this app never changes hardware. Firmware or power management may reset settings at reboot or on other events.

## Authentication

The first setting change opens the system's polkit authentication dialog. After authentication, the app reuses a temporary privileged helper for the rest of that app session. Further profile changes and max/automatic fan toggles do not prompt again. **Lock Fan Controls** in the menu ends the session immediately; the next change asks again. Closing the window also ends it. If the helper crashes or the connection is lost, a new authorization may be needed.

The UI and RPM monitoring stay unprivileged. The host's Python runs the app's small helper in isolated mode (`-I`), with a private stdin/stdout pipe. The helper accepts only four named thermal profiles and maximum/automatic fan modes. It discovers HP sysfs paths itself and never accepts paths, executable names, or code from protocol messages. It cannot create arbitrary files or follow a substituted sysfs attribute symlink. Both client and helper validate settings.

The helper exits on pipe closure; a 20-second heartbeat timeout bounds its lifetime after an unexpected disconnect. Flatpak also uses `flatpak-spawn --host --watch-bus`. No daemon, host-package installation, passwordless rule, permission change, or system-wide polkit policy is installed. The administrator prompt may describe running Python: that interpreter runs the app's fixed fan helper. Your password is handled by polkit, never the app. Cancelling authentication leaves cooling unchanged.

Firmware settings themselves remain active when the authorization session closes; locking does not change the selected cooling mode. The kernel and firmware retain their thermal protections.

## Preview and checks

```sh
# Interactive preview with in-memory data; never accesses hardware
/usr/bin/python3 -m fan_control --demo

# Hardware discovery, validation, and readback tests using a temporary sysfs tree
/usr/bin/python3 -m unittest discover -s tests -v

# Exercise the real GTK controls in preview mode, then exit
/usr/bin/python3 -m fan_control --smoke-test

# Exercise async writes, cancellation, and failures against temporary files
/usr/bin/python3 tests/gui_integration.py

# Also save a screenshot of the preview window
/usr/bin/python3 -m fan_control --smoke-test --screenshot /tmp/fan-control.png
```

## Uninstall

```sh
flatpak uninstall --user io.github.sh7vansh.VictusFanControl
```

Removing the app does not change the current firmware settings. The source checkout and distributable bundle are independent of the installed app.

## References

* [Linux platform profile interface](https://docs.kernel.org/userspace-api/sysfs-platform_profile.html)
* [HP WMI driver](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/hp/hp-wmi.c), including `PWM_MODE_MAX = 0`, `PWM_MODE_AUTO = 2`, CPU fan 0, GPU fan 1.
* [libadwaita widgets](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/)

[MIT license](LICENSE).
