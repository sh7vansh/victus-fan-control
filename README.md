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

The app uses `flatpak-spawn --host` to read hardware and configure a systemd service. **This permits commands outside the sandbox as your user**, which GNOME Software labels “Potentially Unsafe.” Select **Enable Service** on first use and authenticate through polkit. Cooling changes then use a local socket without repeated prompts. See [packaging details](packaging/README.md).

Requires supported HP firmware, Flatpak, systemd, polkit (`pkexec`), coreutils, and a graphical authentication agent on the host. The static Go helper is bundled; host Python and Go are not required. The GNOME 51 runtime is supplied by Flathub. Screenshots show live readings from an HP Victus; fan speeds and available controls vary by laptop.

[Project page](https://sh7vansh.github.io/victus-fan-control/) · [Releases](https://github.com/sh7vansh/victus-fan-control/releases) · [Report a problem](https://github.com/sh7vansh/victus-fan-control/issues)

Find **Fan Control** in the GNOME app grid after installation. It follows GNOME's light/dark appearance and accent color. Resize the window to fit; the controls scroll when needed. Ctrl+Q closes the app.

## Run from source for development

On Fedora, use the system Python. Dependencies: `python3-gobject`, `gtk4`, `libadwaita`, and `polkit`. These are already installed on the target laptop. If needed:

```sh
sudo dnf install python3-gobject gtk4 libadwaita polkit
```

For source development, also install Go 1.22+ and build the helper. Flatpak users do not need the compiler. From this directory:

```sh
/usr/bin/python3 packaging/build_helper.py --test
/usr/bin/python3 -m fan_control
```

Source runs use the same system service. Enable it from the app after building the helper. Tested with GTK 4.22 and libadwaita 1.9.

## What the controls do

* **Quiet, Cool, Balanced, Performance:** write the selected profile to `/sys/firmware/acpi/platform_profile`. Only profiles reported by `platform_profile_choices` are enabled. These are firmware policies affecting power and thermals together, not custom fan curves or direct RPM targets.
* **Max fan speed on:** writes `0` to the HP controller's `pwm1_enable`.
* **Max fan speed off:** writes `2` to restore firmware automatic fan control.
* **RPM:** reads `fan1_input` and `fan2_input` from the HP controller. Uses firmware labels when exposed, otherwise CPU fan / GPU fan (the HP driver's fan order). Zero is shown as stopped; missing or unreadable readings are shown as unavailable.

The controller is discovered by its `hp` hwmon name and `hp-wmi` platform path, so `hwmon` numbering may change after reboot. The app polls the actual state and reflects changes from GNOME, TuneD, firmware, or other apps. It does not continuously reapply settings or disable the system's power manager. If a setting is immediately overridden, readback reports that it did not stay applied. GNOME power modes and firmware thermal profiles are separate interfaces; their mapping depends on the power manager.

**Settings remain in firmware when the window closes.** To end a max fan burst, turn off Max fan speed before closing. Closing or reopening this app never changes hardware. Firmware or power management may reset settings at reboot or on other events.

## Background service and authentication

Cooling changes require the system service. Select **Enable Service** in the banner or **Background Service…** in the menu. Polkit authenticates the installation, which copies the bundled helper to `/usr/local/libexec/victus-fan-control/helper`, owned by root, and installs `/etc/systemd/system/victus-fan-control.service`. The persistent service never executes from your writable checkout or Flatpak deployment. Your password is handled by polkit, never by the app. Cancelling installation leaves hardware settings unchanged.

The service starts at boot. Its `/run/victus-fan-control.sock` socket has mode `0600`, is owned by the account that enabled the service, and checks kernel peer credentials. Only that account and root may send commands. Enabling or updating from another account transfers access to that account. All processes running as the authorized user share this permission; it is not limited to this app. The daemon accepts only four named thermal profiles and maximum/automatic fan modes, discovers sysfs paths itself, and never accepts paths, executable names, or code in protocol messages.

The UI, RPM monitoring, and readback remain unprivileged. Closing the app closes its connection; the daemon stays active. **Disable Service** stops it and removes its unit and installed helper, without changing firmware settings. The previous Lock Fan Controls action and per-session authentication are no longer used.

After updating the app, choose **Background Service… → Update Service** to replace the root-owned helper with the bundled version. This also migrates older service installations to the restricted socket and root-owned executable. Flatpak users must restart the app after enabling or updating the service so its sandbox sees the new socket. Connection, greeting, and reply failures are bounded by a timeout and reported in the UI.

The compiled Go helper has cgo disabled and no host interpreter or dynamic C library dependency. Both client and helper validate settings; the helper cannot create missing sysfs attributes or follow a substituted attribute symlink. Firmware settings remain active after disconnecting or disabling the service. The kernel and firmware retain their thermal protections.

## Preview and checks

```sh
# Interactive preview with in-memory data; never accesses hardware
/usr/bin/python3 -m fan_control --demo

# Build/test the compiled helper and its separate test fixture executable
/usr/bin/python3 packaging/build_helper.py --test

# Hardware discovery, validation, and readback tests using a temporary sysfs tree
/usr/bin/python3 -m unittest discover -s tests -v

# Exercise the real GTK controls in preview mode, then exit
/usr/bin/python3 -m fan_control --smoke-test

# Exercise daemon writes, reconnects, and failures against temporary files
/usr/bin/python3 tests/gui_integration.py
/usr/bin/python3 tests/gui_host.py

# Also save a screenshot of the preview window
/usr/bin/python3 -m fan_control --smoke-test --screenshot /tmp/fan-control.png
```

## Uninstall

First choose **Background Service… → Disable Service** to remove the host service and helper. Flatpak cannot remove these host files automatically. Then uninstall the app:

```sh
flatpak uninstall --user io.github.sh7vansh.VictusFanControl
```

Removing the app does not change the current firmware settings. The source checkout and distributable bundle are independent of the installed app.

## References

* [Linux platform profile interface](https://docs.kernel.org/userspace-api/sysfs-platform_profile.html)
* [HP WMI driver](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/hp/hp-wmi.c), including `PWM_MODE_MAX = 0`, `PWM_MODE_AUTO = 2`, CPU fan 0, GPU fan 1.
* [Flatpak deployment paths](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-metadata), using the runtime-provided `Instance/app-path`.
* [libadwaita widgets](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/)

[MIT license](LICENSE). The bundled Go runtime uses the [Go BSD license](data/licenses/Go-LICENSE).
