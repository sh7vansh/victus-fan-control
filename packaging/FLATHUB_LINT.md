# Flathub lint status

Checked on 2026-10-17 with the official `ghcr.io/flathub/flatpak-builder-lint` container, version `3.0.0.post897.dev0+c85243b`.

| Check | Result |
| --- | --- |
| AppStream metadata | Pass |
| Manifest, strict | Only `finish-args-flatpak-spawn-access` remains |
| Flathub-style repository, strict | Only `finish-args-flatpak-spawn-access` remains |
| Manifest, permission-review mode | Pass, with the host-execution warning |
| Flathub-style repository, permission-review mode | Pass, with the host-execution warning |

No local exceptions are applied. Permission-review mode is an official linter option that reports reviewable permissions as warnings; it does not grant permission approval or establish Flathub eligibility.

## Fixed

- The app ID is now `io.github.sh7vansh.victus-fan-control`, which maps to the actual GitHub repository.
- The manifest uses a source Git commit instead of a local directory. It was also checked with Flathub new-submission source checks enabled.
- The candidate uses AppStream's full composer to download and rewrite screenshots, retains the expected catalog filename, and commits the media to `screenshots/x86_64`.
- The signed self-hosted update repository preserves its collection identity and rebases old-ID installations to the new ID. This migration was tested with an isolated old-ID installation. The OMEN shortcut updates its old launcher command while preserving customizations and disabled bindings.

## Remaining permission

The app uses `flatpak-spawn --host` for hardware discovery/readback, administrator-approved service installation and management, and GNOME shortcut setup. Removing its manifest permission would break those functions. Eliminating it requires changing the architecture and provisioning flow; suppressing its linter error would not fix it.

Flathub acceptance and current exception/AI policies are separate from these technical results. This check does not prepare or submit an exception request or Flathub submission.

## Reproduce

```sh
/usr/bin/python3 packaging/check_flathub.py
```

Requires Podman, Flatpak with GNOME 51 Platform, and Go. It stages the current checkout, composes media in the official linter container, exports a temporary repository, and saves raw results under `build/flathub-lint/`. The command exits nonzero while strict lint still reports host execution. The Flathub media URLs are build outputs for eventual Flathub hosting, not URLs deployed by this script.

The self-hosted release continues to use its working GitHub screenshot URLs. Running Flathub's repository linter on that self-hosted repository therefore still reports Flathub-specific screenshot-hosting errors; the Flathub candidate uses the required media pipeline instead.

References: [linter rules](https://docs.flathub.org/docs/for-app-authors/linter), [submission requirements](https://docs.flathub.org/docs/for-app-authors/requirements).
