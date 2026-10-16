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

Verified on 2026-10-16 using the public Pages repository and GNOME Software 50.4. Actual reference-import output includes:

```text
quirk:               local-has-repository
name:                Fan Control
version:             1.0.2
license:             MIT
license-is-free:     yes
size-download:       262.6 kB
size-installed:      312.3 kB
```

The same consumer result includes a cached app icon, the full description, two screenshot URLs, and the public homepage. Both screenshot URLs and the homepage return HTTP 200. GNOME Software's text diagnostic prints only the homepage URL, while the repository metadata includes homepage, source, and issue-tracker links. An isolated temporary Flatpak installation verified the signed remote and catalog. No application was installed.

The signed repository and `.flatpakref` are now the primary distribution. They supply the remote catalog, MIT license, hosted screenshots, project links, sizes, and application updates through GNOME Software's full reference-import path. Run `packaging/check_software_page.py dist/fan-control.flatpakref` against the published repository to verify the consumer result.

The separate `.flatpak` remains useful for offline transfer but can still show incomplete details in GNOME Software 50.4. Use the reference when viewing the complete installer listing.

“Potentially Unsafe / Can acquire arbitrary permissions” remains correct: the selected host-command design permits commands outside the sandbox. Signing and metadata do not remove that permission. A narrower design would require a separately installed host service, which this package does not use.

## Icon and screenshot refresh after installation

A Software window which predates the first installation can retain a generic icon even though both installed AppStream icon files match the custom fan artwork. In the observed case, closing and reopening GNOME Software restored the fan icon; the user confirmed the corrected rendering. No icon asset replacement was needed.

Version 1.0.3 replaces preview captures with live, read-only hardware screenshots. The listing checker now verifies cached icon content and exact source screenshot URLs. It reproduced a stale gallery by failing on the old preview URLs, then passes after refreshing only the Fan Control AppStream catalog and reopening Software. The installed application need not be updated to refresh the catalog.

## Session authorization in 1.1.0

The previous per-write `pkexec tee` flow is replaced by an app-session helper. The first change authenticates; later changes use a private, enumerated protocol. Lock Fan Controls or window close ends the session. The helper is not installed as a system service. A missing heartbeat expires an idle helper within 20 seconds; a crash or disconnected helper requires a new authorization on the next attempt.

Real polkit startup and EOF shutdown were tested on the Fedora target using only heartbeat messages and one authentication. Hardware writes in the new protocol were tested against temporary sysfs; the automated suite does not claim real authenticated firmware writes on every laptop. See packaging/README.md for the current design; older per-write examples in the original distribution research describe the earlier release.
