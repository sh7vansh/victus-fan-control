# Flatpak packaging

Fan Control ships as a Flatpak with a static Go helper. Read-only discovery and verification run the bundled helper as the current user. Cooling writes use a systemd daemon installed through **Background Service… → Enable Service** and a polkit prompt. Installation copies the executable into root-owned `/usr/local/libexec/victus-fan-control/helper` and creates `/etc/systemd/system/victus-fan-control.service`; a persistent root unit must never execute from a writable checkout or per-user Flatpak deployment.

The host needs Flatpak, systemd, polkit (`pkexec`), coreutils, and a graphical authentication agent. Host Python and Go are not needed; Python for the UI comes from the GNOME runtime. The helper is built with `CGO_ENABLED=0`, and its ELF program headers are checked for the absence of a dynamic loader. Hardware support depends on HP firmware and the Linux driver.

## Permissions and service lifecycle

`--talk-name=org.freedesktop.Flatpak` allows commands as the host user outside the sandbox. Host commands can access user files, so the sandbox is not a security boundary against this app. GNOME Software's “Potentially Unsafe” warning is accurate. Wayland, fallback X11, IPC, graphics rendering, desktop power-profile D-Bus access, and `/run/victus-fan-control.sock` access are also enabled.

Enabling the service requires administrator authentication and records the enabling account's numeric UID. The daemon creates a mode `0600` socket owned by that account and checks `SO_PEERCRED` before sending the protocol greeting. Only that UID and root are accepted. The permission applies to all processes with that UID. Enabling or updating from a different account transfers access. The protocol permits only enumerated thermal profile and maximum/automatic fan operations; it accepts no client paths or executable commands.

The service runs at boot and survives app closure and Flatpak updates. Choose **Update Service** after updating the app to refresh its root-owned helper and migrate old units. Installation atomically stages files and restarts an already running service. Flatpak must be restarted after enabling or updating, because its sandbox can retain the previous socket inode. The client bounds connection, greeting, and reply waits. Cancelled authentication does not alter cooling settings.

Before uninstalling the Flatpak, use **Disable Service** to stop and remove the host unit, socket, and helper. Uninstalling the Flatpak alone leaves the service installed. Disabling the service or closing the app does not reset hardware settings.

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

The final check resolves the published reference through GNOME Software without installing it. CI tests hardware backends and source metadata. GUI tests use temporary hardware files and a real daemon compiled from the Go test sources; desktop power-profile writes are mocked. Go tests cover discovery, request validation, safe sysfs writes, bounded input, EOF/idle shutdown for the legacy session entry point, private daemon socket permissions, peer authorization, and privilege checks. Python tests cover daemon reuse, disconnects, greeting/reply timeouts, failed writes, service completion, and root-owned installation commands. Fixture roots and failure injection exist exclusively in `_test.go` files and are never packaged. Actual service installation, polkit prompts, and real firmware writes still need validation on each supported laptop/driver combination.

The bundle validator inspects embedded metadata/icons. This alone cannot prove the software-center page is complete. For repository signatures/catalog verification without changing normal installations, use a temporary `FLATPAK_USER_DIR` and run only `flatpak --user` commands; see [distribution research](DISTRIBUTION_RESEARCH.md).

Refresh icons with `python3 packaging/generate_icons.py`; see [screenshots](../data/screenshots/README.md) for captures. Max fan speed remains active after closing; turn it off to restore automatic cooling.

## Helper deployment and portability

The packaged executable is `/app/libexec/victus-fan-control-helper`. `fan_control/native.py` obtains its exact host path from the running sandbox's `[Instance] app-path` in `/.flatpak-info`. Reads use argument arrays. The service installer uses a shell script with quoted paths, checks command failures, copies the helper with root ownership, and restores SELinux labels when available. The service uses only the root-owned copy, so deleting or updating a Flatpak deployment does not invalidate its executable.

The helper accepts `--snapshot`, `--verify-profile VALUE`, `--verify-fan VALUE`, `--version`, and root-only `--daemon --allow-uid UID`. The legacy root-only `--session` pipe protocol remains available for protocol tests, but the app no longer uses it. Production does not accept an alternate socket or sysfs root.

Go's cgo support is disabled for the helper; see the [Go cgo documentation](https://go.dev/src/cmd/cgo/doc.go). Build architecture is selected explicitly from the local/SDK architecture. An incompatible CPU architecture or a host filesystem mounted with `noexec` can still prevent execution; static linking does not remove kernel, hardware, or polkit requirements. The Go runtime license is included in the app's licenses directory.
