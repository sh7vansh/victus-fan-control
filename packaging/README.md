# Flatpak packaging

Fan Control is one Flatpak; no host RPM or service is required. Read-only discovery runs host Python as the current user. Changes use `flatpak-spawn --host /usr/bin/pkexec /usr/bin/tee -- <validated sysfs attribute>` with the setting on standard input. Reads and verification are asynchronous. Cancelled authentication restores the actual hardware state in the controls.

The host needs Python 3.10+, polkit, coreutils, and a graphical authentication agent. Hardware support depends on HP firmware and the Linux driver.

## Permission

`--talk-name=org.freedesktop.Flatpak` allows commands as the host user outside the sandbox. It does not grant root; protected writes require polkit authentication. Host commands can access user files, so the sandbox is not a security boundary against this app. GNOME Software's “Potentially Unsafe” warning is accurate. Wayland, fallback X11, IPC, and graphics rendering are also enabled.

## Install

Open [fan-control.flatpakref](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref) in GNOME Software, or use:

```sh
flatpak install --user https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref
flatpak run io.github.sh7vansh.VictusFanControl
flatpak update --user
```

The reference embeds the public key, adds the signed Fan Control update repository, and identifies Flathub as the runtime source. The secondary `.flatpak` bundle includes the repository origin, but [GNOME Software 50.4's bundle importer](KNOWN_ISSUES.md) omits some details. Prefer the reference for the complete listing.

## Build locally

With GNOME 51 Platform installed:

```sh
/usr/bin/python3 packaging/build.py flatpak --test
```

This stages pure Python using the installed Platform, so no SDK or flatpak-builder download is needed. It creates an unsigned development bundle under `dist/` and a development repository under `build/development-repo/`. The smoke test uses simulated readings; building does not install the app or alter fans. Omit `--test` without a graphical session.

The conventional `io.github.sh7vansh.VictusFanControl.json` manifest also works with flatpak-builder and `org.gnome.Sdk//51`:

```sh
flatpak-builder --user --install-deps-from=flathub --repo=repo build/flatpak io.github.sh7vansh.VictusFanControl.json
```

## Signed release

The initial repository uses public-key fingerprint `03B3FEDB63A63601DBA151349836F000D7922580`. Keep its private key backed up securely outside Git. Losing it prevents seamless updates using the existing trust identity. Do not generate a new key for each release or publish a private key.

Before releasing, update the Python version and MetaInfo release, capture screenshots if the UI changed, and pin screenshot URLs to a release tag. Run the checks below, commit the source, and push the tag before validating URLs.

For the initial publisher, the dedicated key directory is `~/.local/share/victus-fan-control-release-keys`. The directory is private and is not part of the repository. Build with:

```sh
/usr/bin/python3 packaging/build.py flatpak --test \
  --signing-key 03B3FEDB63A63601DBA151349836F000D7922580 \
  --gpg-homedir ~/.local/share/victus-fan-control-release-keys
```

The signed site/repository is `build/public/`. Both application commits and the summary are signed; AppStream and static deltas are generated. Reference files and the signing public key are also copied to `dist/`. Never mix unsigned development exports into the public repository.

The GitHub Pages source is the `gh-pages` branch. Preserve the existing repository history for future updates. On a new checkout, clone that branch into `build/public` **before building**:

```sh
mkdir -p build
git clone --single-branch --branch gh-pages git@github.com:sh7vansh/victus-fan-control.git build/public
```

After the signed build, review and commit the generated changes in `build/public`, push `gh-pages`, and attach the `.flatpakref`, `.flatpakrepo`, public key, bundle, and SHA256 checksums to the GitHub release. The root `.nojekyll` preserves static OSTree files. Pages hosts the repository at `https://sh7vansh.github.io/victus-fan-control/repo/`. Use `flatpak update --user` for installed applications.

## Verify

```sh
/usr/bin/python3 -m unittest discover -s tests -v
appstreamcli validate --no-net data/io.github.sh7vansh.VictusFanControl.metainfo.xml
/usr/bin/python3 tests/gui_integration.py
/usr/bin/python3 tests/gui_host.py
/usr/bin/python3 packaging/verify_bundle.py dist/io.github.sh7vansh.VictusFanControl-x86_64.flatpak
/usr/bin/python3 packaging/check_software_page.py dist/fan-control.flatpakref
```

The final check resolves the published reference through GNOME Software without installing it. CI tests the hardware backends and validates source metadata; it does not exercise real authorization or firmware. GUI tests use temporary files or preview data. Manual authentication and real writes still need testing on each supported laptop/driver combination.

The bundle validator inspects embedded metadata/icons. This alone cannot prove the software-center page is complete. For repository signatures/catalog verification without changing normal installations, use a temporary `FLATPAK_USER_DIR` and run only `flatpak --user` commands; see [distribution research](DISTRIBUTION_RESEARCH.md).

Refresh icons with `python3 packaging/generate_icons.py`; see [screenshots](../data/screenshots/README.md) for captures. Max fan speed remains active after closing; turn it off to restore automatic cooling.
