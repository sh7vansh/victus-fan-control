# Packaging

The Flatpak bundles the Python UI and a static Go helper. It uses GNOME Platform 51; the host needs Flatpak, systemd, polkit, coreutils, and a graphical authentication agent.

## Build

With GNOME Platform 51 and Go 1.22+ installed:

```sh
/usr/bin/python3 packaging/build.py flatpak --test
```

This builds the checkout into `dist/` and `build/development-repo/`. Omit `--test` without a graphical session.

The manifest builds its pinned source commit using GNOME SDK 51 and the matching Go SDK extension:

```sh
flatpak-builder --user --install-deps-from=flathub --repo=repo \
  build/flatpak io.github.sh7vansh.victus-fan-control.json
```

## Host service

**Enable Service** uses polkit to install:

- `/usr/local/libexec/victus-fan-control/helper`, owned by root.
- `/etc/systemd/system/victus-fan-control.service`.

The service starts at boot and accepts cooling requests through `/run/victus-fan-control.sock`. The socket has mode `0600`; kernel peer credentials restrict access to the enabling account and root. Any process running as that account has access. Enabling the service from another account transfers ownership.

The helper accepts four thermal profiles and maximum/automatic fan modes. It discovers sysfs paths itself. Reads and readback run as the user; writes go through the service. The Flatpak locates its bundled helper through `Instance/app-path` in `/.flatpak-info`.

**Update Service** replaces the installed helper. Restart the Flatpak afterward so it sees the new socket. **Disable Service** removes the unit and helper; uninstalling the Flatpak alone leaves them installed. Neither closing the app nor removing the service resets cooling settings.

Host reads, service management, and GNOME shortcut setup use `flatpak-spawn --host`. The OMEN shortcut uses `Launch2`, preserves existing assignments, and can be changed in GNOME Settings. It remains after uninstalling the app.

## Checks

```sh
/usr/bin/python3 packaging/build_helper.py --test
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 tests/gui_integration.py
/usr/bin/python3 tests/gui_host.py
appstreamcli validate --no-net data/io.github.sh7vansh.victus-fan-control.metainfo.xml
/usr/bin/python3 packaging/verify_bundle.py dist/io.github.sh7vansh.victus-fan-control-x86_64.flatpak
/usr/bin/python3 packaging/check_software_page.py dist/fan-control.flatpakref
```

The GUI tests use temporary sysfs files and a test daemon. The last command checks the installer listing in GNOME Software. See [known issues](KNOWN_ISSUES.md) and [Flathub lint status](FLATHUB_LINT.md).

## Release

Keep the existing signing key and `gh-pages` history so installed apps can verify updates. On a fresh checkout, clone the public repository before building:

```sh
mkdir -p build
git clone --single-branch --branch gh-pages git@github.com:sh7vansh/victus-fan-control.git build/public
```

Update the version in `fan_control/__init__.py` and MetaInfo, commit the source, then update the manifest's source commit. Refresh [screenshots](../data/screenshots/README.md) if the UI changed.

```sh
/usr/bin/python3 packaging/build.py flatpak --test \
  --signing-key 03B3FEDB63A63601DBA151349836F000D7922580 \
  --gpg-homedir ~/.local/share/victus-fan-control-release-keys
```

Commit and push `build/public/` to `gh-pages`. Attach the `.flatpakref`, `.flatpakrepo`, public key, bundle, and fresh SHA256 checksums from `dist/` to the GitHub release. The private key stays outside the repository.

To verify a release separately from installed apps, set `FLATPAK_USER_DIR` to a temporary directory and use `flatpak --user` for every command.

### App ID migration

Version 1.5.0 changed the ID from `io.github.sh7vansh.VictusFanControl` to `io.github.sh7vansh.victus-fan-control`. Signed builds retain the old collection ID and mark the old app ref for rebase. Keep that migration in future releases. On first launch, the new app updates its old OMEN shortcut command while preserving user edits.
