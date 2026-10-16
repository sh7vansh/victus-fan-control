# Application screenshots

These are captures of the live GTK/libadwaita window on an HP Victus:

* `fan-control-light.png`: light appearance, Balanced profile, and automatic cooling.
* `fan-control-dark.png`: dark appearance of the same controls.

Both images are 520 × 820 pixels. Fan RPM readings are real examples at capture time and vary with workload and temperature.

Regenerate from the project root on a GNOME desktop with supported hardware. The capture tool only reads sensors and never activates controls or changes settings:

```sh
/usr/bin/python3 packaging/capture_screenshot.py light
/usr/bin/python3 packaging/capture_screenshot.py dark
```

The images are included in the Flatpak under `/app/share/victus-fan-control/data/screenshots/` for distribution with the app. Flatpak bundles embed installer icons and AppStream XML, but do not embed a software-center screenshot gallery. Software centers load screenshot image URLs from AppStream. Copying PNG files into the bundle does not make them visible before installation.

The MetaInfo references the images at commit-pinned HTTPS URLs in the public GitHub repository. When replacing screenshots, update the pinned commit and dimensions in `data/io.github.sh7vansh.VictusFanControl.metainfo.xml` and `packaging/site/index.html`, then push that commit before validating the installer. The catalog composer preserves screenshot metadata.
