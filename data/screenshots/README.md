# Application screenshots

These are captures of the real GTK/libadwaita window, using clearly labeled preview data:

* `fan-control-light.png`: light appearance, Balanced profile, and automatic cooling.
* `fan-control-dark.png`: dark appearance of the same controls.

Both images are 520 × 900 pixels. No screenshot is presented as a measurement from a particular laptop.

Regenerate from the project root on a GNOME desktop:

```sh
/usr/bin/python3 packaging/capture_screenshot.py light
/usr/bin/python3 packaging/capture_screenshot.py dark
```

The images are included in the Flatpak under `/app/share/victus-fan-control/data/screenshots/` for distribution with the app. Flatpak bundles embed installer icons and AppStream XML, but do not embed a software-center screenshot gallery. Software centers load screenshot image URLs from AppStream. Copying PNG files into the bundle does not make them visible before installation.

The MetaInfo references the images at tag-pinned HTTPS URLs in the public GitHub repository. When replacing screenshots, update the pinned tag and dimensions in `data/io.github.sh7vansh.VictusFanControl.metainfo.xml` and `packaging/site/index.html`, then publish that tag before validating the installer. The catalog composer preserves screenshot metadata.
