# Known issues

## Incomplete listing for local bundles

GNOME Software 50.4 can show an unknown license and omit details when opening a `.flatpak` bundle, even when its embedded metadata is valid. Use the [`.flatpakref` installer](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref) for the full listing and updates.

The [bundle importer](https://github.com/GNOME/gnome-software/blob/50.4/plugins/flatpak/gs-flatpak.c#L4006) requests only ID refinement. The [AppStream reader](https://github.com/GNOME/gnome-software/blob/50.4/lib/gs-appstream.c#L1201) requires a separate flag to populate the license. The reference importer uses the remote catalog and requests full refinement.

Check either format with:

```sh
/usr/bin/python3 packaging/check_software_page.py dist/fan-control.flatpakref
```

Pass the `.flatpak` path instead to reproduce the bundle-import issue.

## Stale icons or screenshots

Reopen GNOME Software after refreshing the Fan Control repository catalog. The listing checker compares cached icon contents and screenshot URLs with the current source metadata.

## Service active but controls cannot connect

Restart the Flatpak after enabling or updating the service. Its sandbox may still have the previous socket mounted. Check the service with:

```sh
systemctl status victus-fan-control.service
```
