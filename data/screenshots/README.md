# Screenshots

`fan-control-light.png` and `fan-control-dark.png` show the live app on an HP Victus. Both are 520 × 820 pixels.

Capture them from the project root on GNOME with supported hardware:

```sh
/usr/bin/python3 packaging/capture_screenshot.py light
/usr/bin/python3 packaging/capture_screenshot.py dark
```

The tool reads sensors without changing cooling settings. RPM values vary with workload.

After committing new images, pin their commit and dimensions in the MetaInfo file and `packaging/site/index.html`. Software centers load the screenshots from those URLs, so push the image commit before checking the listing.
