# Fan Control

A GTK 4 / libadwaita app for supported HP Victus and OMEN laptops on Linux. Choose a thermal profile, toggle maximum fan speed, and monitor both fans' RPM.

<p>
  <img src="data/screenshots/fan-control-light.png" alt="Light appearance" width="280">
  <img src="data/screenshots/fan-control-dark.png" alt="Dark appearance" width="280">
</p>

## Install

Open the [Flatpak installer](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref), or run:

```sh
flatpak install --user https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref
flatpak run io.github.sh7vansh.VictusFanControl
```

Select **Enable Service**, authenticate, and restart the app when prompted. Requires compatible HP firmware, `hp-wmi`, systemd, and polkit.

## Use

- **Thermal profile:** choose Quiet, Cool, Balanced, or Performance where supported.
- **Max fan speed:** turn on for maximum cooling; turn off for automatic control.
- **RPM:** both fan readings refresh every second.

**Closing the app leaves settings active.** Turn off maximum fan speed to restore automatic cooling.

## How it works

The Python UI reads Linux hardware interfaces; a root-owned Go service applies changes through a private local socket. Supported profile changes also try to update GNOME's power mode. No custom fan curves or exact RPM targets.

The Flatpak can run commands as your host user, so GNOME Software labels it **“Potentially Unsafe.”** After app updates, choose **Background Service… → Update Service** and restart the app.

## Development

On Fedora, install `python3-gobject gtk4 libadwaita polkit golang`, then run:

```sh
/usr/bin/python3 packaging/build_helper.py --test
/usr/bin/python3 -m fan_control
```

Use `--demo` for a preview without hardware access. See [packaging details](packaging/README.md) for builds, tests, and service permissions.

## Uninstall

Choose **Background Service… → Disable Service** first, then run:

```sh
flatpak uninstall --user io.github.sh7vansh.VictusFanControl
```

[Report a problem](https://github.com/sh7vansh/victus-fan-control/issues) · [MIT license](LICENSE) · [Go runtime license](data/licenses/Go-LICENSE)
