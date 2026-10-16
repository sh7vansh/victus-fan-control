# Fan Control

Fan controls for HP Victus and OMEN laptops on Linux, built with GTK 4 and libadwaita.

<p>
  <img src="data/screenshots/fan-control-light.png" alt="Light appearance" width="280">
  <img src="data/screenshots/fan-control-dark.png" alt="Dark appearance" width="280">
</p>

## Install

Open the [Flatpak installer](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref), or run:

```sh
flatpak install --user https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref
flatpak run io.github.sh7vansh.victus-fan-control
```

Choose **Enable Service**, authenticate, and restart when prompted. Requires supported HP firmware, `hp-wmi`, systemd, and polkit. The app runs commands on the host, which GNOME Software labels “Potentially Unsafe.”

## Controls

- Choose Quiet, Cool, Balanced, or Performance where supported by firmware.
- Toggle maximum fan speed or return to automatic control.
- Monitor both fans' RPM, refreshed every second.

**Maximum fan speed stays active after closing.** Turn it off to restore automatic cooling.

On GNOME, the OMEN button opens the app if the key was unassigned. Change it in Settings → Keyboard → Custom Shortcuts.

After updating, choose **Background Service… → Update Service** and restart. Before uninstalling, choose **Disable Service** to remove the host service.

## Development

On Fedora, install `python3-gobject gtk4 libadwaita polkit golang`, then run:

```sh
/usr/bin/python3 packaging/build_helper.py --test
/usr/bin/python3 -m fan_control
```

Use `--demo` to preview with simulated readings. See [packaging](packaging/README.md) for builds, tests, and releases.

[Issues](https://github.com/sh7vansh/victus-fan-control/issues) · [MIT license](LICENSE) · [Go runtime license](data/licenses/Go-LICENSE)
