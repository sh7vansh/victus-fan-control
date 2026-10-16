# Flatpak packaging

Fan Control is one Flatpak; no host RPM or service is required. Read-only discovery and verification use the bundled static Go helper as the current user. The first change starts `flatpak-spawn --host --watch-bus /usr/bin/pkexec --disable-internal-agent <deployment>/files/libexec/victus-fan-control-helper --session`. After one authentication, subsequent changes use its private pipe. The helper accepts only enumerated thermal profile and maximum/automatic fan operations; it discovers sysfs paths itself and accepts no client paths or executable commands. It exits on pipe closure, manual locking, or a 20-second heartbeat timeout after loss of the client. The helper runs directly from the Flatpak deployment; no separate executable is copied or installed elsewhere on the host. Reads and verification are asynchronous. Cancelled authentication restores the actual hardware state in the controls.

The host needs Flatpak, polkit (`pkexec`), and a graphical authentication agent. Python, Go, and coreutils are not app dependencies on the host; Python for the UI comes from the GNOME runtime. The helper is built for the Flatpak architecture with `CGO_ENABLED=0`, and its ELF program headers are checked for the absence of a dynamic loader. Hardware support depends on HP firmware and the Linux driver.

## Permission

`--talk-name=org.freedesktop.Flatpak` allows commands as the host user outside the sandbox. It does not grant root; the temporary privileged helper requires polkit authentication once per app session. Host commands can access user files, so the sandbox is not a security boundary against this app. GNOME Software's “Potentially Unsafe” warning is accurate. Wayland, fallback X11, IPC, and graphics rendering are also enabled.

## Install

Open [fan-control.flatpakref](https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref) in GNOME Software, or use:

```sh
flatpak install --user https://sh7vansh.github.io/victus-fan-control/fan-control.flatpakref
flatpak run io.github.sh7vansh.VictusFanControl
flatpak update --user
```

The reference embeds the public key, adds the signed Fan Control update repository, and identifies Flathub as the runtime source. The secondary `.flatpak` bundle includes the repository origin, but [GNOME Software 50.4's bundle importer](KNOWN_ISSUES.md) omits some details. Prefer the reference for the complete listing.

## Build locally

With GNOME 51 Platform and a local Go 1.22+ compiler installed:

```sh
/usr/bin/python3 packaging/build.py flatpak --test
```

This compiles the helper locally, then stages the Python UI and helper using the installed Platform. No SDK or flatpak-builder download is needed for this local route. Go builds use only the standard library with `GOPROXY=off` and `GOTOOLCHAIN=local`; no external Go modules or compiler downloads are used. It creates an unsigned development bundle under `dist/` and a development repository under `build/development-repo/`. The smoke test uses simulated readings; building does not install the app or alter fans. Omit `--test` without a graphical session.

The conventional `io.github.sh7vansh.VictusFanControl.json` manifest also works with flatpak-builder, `org.gnome.Sdk//51`, and the matching `org.freedesktop.Sdk.Extension.golang` extension:

```sh
flatpak-builder --user --install-deps-from=flathub --repo=repo build/flatpak io.github.sh7vansh.VictusFanControl.json
```

## Signed release

The initial repository uses public-key fingerprint `03B3FEDB63A63601DBA151349836F000D7922580`. Keep its private key backed up securely outside Git. Losing it prevents seamless updates using the existing trust identity. Do not generate a new key for each release or publish a private key.

Before releasing, update the Python version and MetaInfo release, capture screenshots if the UI changed, and pin screenshot URLs to a published commit. Run the checks below, commit the source, and push the referenced commit before validating URLs.

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
/usr/bin/python3 packaging/build_helper.py --test
/usr/bin/python3 -m unittest discover -s tests -v
appstreamcli validate --no-net data/io.github.sh7vansh.VictusFanControl.metainfo.xml
/usr/bin/python3 tests/gui_integration.py
/usr/bin/python3 tests/gui_host.py
/usr/bin/python3 packaging/verify_bundle.py dist/io.github.sh7vansh.VictusFanControl-x86_64.flatpak
/usr/bin/python3 packaging/check_software_page.py dist/fan-control.flatpakref
```

The final check resolves the published reference through GNOME Software without installing it. CI tests the hardware backends and validates source metadata; it does not exercise real authorization or firmware. On the target Fedora laptop, the real pkexec helper startup, repeated heartbeat messages, and clean EOF shutdown were verified with one authentication and no hardware writes. GUI tests use temporary files or preview data. Go tests cover discovery, request validation, bounded input, safe sysfs writes, EOF/idle shutdown, and privilege checks. Python session tests use a separate compiled test executable against temporary sysfs. Its alternate root and failure injection exist exclusively in `_test.go` files and are not included in the production helper. These tests cover reuse, locking, EOF, heartbeat expiry, cancellation, rejected writes, malformed requests, missing attributes, symlinks, timeouts, and crashes. Manual authentication and real writes still need testing on each supported laptop/driver combination.

The bundle validator inspects embedded metadata/icons. This alone cannot prove the software-center page is complete. For repository signatures/catalog verification without changing normal installations, use a temporary `FLATPAK_USER_DIR` and run only `flatpak --user` commands; see [distribution research](DISTRIBUTION_RESEARCH.md).

Refresh icons with `python3 packaging/generate_icons.py`; see [screenshots](../data/screenshots/README.md) for captures. Max fan speed remains active after closing; turn it off to restore automatic cooling.

## Helper deployment and portability

The packaged executable is `/app/libexec/victus-fan-control-helper`. `fan_control/native.py` obtains its exact host path from the running sandbox's `[Instance] app-path` in `/.flatpak-info`, documented by [Flatpak](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-metadata). No host command is needed to discover this path, and it remains pinned to the running deployment across updates. Host commands are argument arrays with no shell, even if the path contains spaces. The helper accepts `--snapshot`, `--verify-profile VALUE`, `--verify-fan VALUE`, `--version`, and the root-only `--session`.

Go's cgo support is disabled for the helper; see the [Go cgo documentation](https://go.dev/src/cmd/cgo/doc.go). Build architecture is selected explicitly from the local/SDK architecture. An incompatible CPU architecture or a host filesystem mounted with `noexec` can still prevent execution; static linking does not remove kernel, hardware, or polkit requirements. The Go runtime license is included in the app's licenses directory.
