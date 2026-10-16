# GNOME Software local-bundle details

Verified against Fedora's GNOME Software 50.4 on 2026-10-16. The app remains uninstalled during these checks.

## Unknown license despite embedded MIT metadata

The `.flatpak` bundle contains `<project_license>MIT</project_license>`. LibAppStream parses it correctly, but GNOME Software's local file inspection returns no license, reproducing the Unknown License tile.

Reproduce through the actual consumer:

```sh
/usr/bin/python3 packaging/check_software_page.py dist/io.github.sh7vansh.VictusFanControl-x86_64.flatpak
```

Expected result on this affected version:

```text
name:                Fan Control
version:             1.0.1
summary:             Manage cooling on HP Victus and OMEN laptops
FAIL: GNOME Software does not recognize the bundle's MIT license.
```

The same check fails on a freshly named temporary copy, ruling out filename caching. This command is a diagnostic for the consumer limitation; it is not part of the bundle's successful metadata validation.

In [GNOME Software 50.4's local bundle importer](https://github.com/GNOME/gnome-software/blob/50.4/plugins/flatpak/gs-flatpak.c#L4006), the embedded catalog is read with `GS_PLUGIN_REFINE_REQUIRE_FLAGS_ID`. [Its AppStream reader](https://github.com/GNOME/gnome-software/blob/50.4/lib/gs-appstream.c#L1201) populates the license only when `GS_PLUGIN_REFINE_REQUIRE_FLAGS_LICENSE` is set. The local-bundle route therefore omits the license even when a caller requests it. Description and screenshot refinement are also gated by their own flags.

Changing the license string or claiming success from XML inspection does not fix this installer behavior. A repository-backed distribution supplies a normal catalog for refinement; the alternative is an upstream GNOME Software fix. Do not patch the user's software center or change package permissions to disguise the missing field.

## Published installer

The signed repository and `.flatpakref` are now the primary distribution. They supply the remote catalog, MIT license, hosted screenshots, project links, sizes, and application updates through GNOME Software's full reference-import path. Run `packaging/check_software_page.py dist/fan-control.flatpakref` against the published repository to verify the consumer result.

The separate `.flatpak` remains useful for offline transfer but can still show incomplete details in GNOME Software 50.4. Use the reference when viewing the complete installer listing.

“Potentially Unsafe / Can acquire arbitrary permissions” remains correct: the selected host-command design permits commands outside the sandbox. Signing and metadata do not remove that permission. A narrower design would require a separately installed host service, which this package does not use.
