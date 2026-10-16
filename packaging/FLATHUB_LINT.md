# Flathub lint

Run with Podman, Flatpak, GNOME Platform 51, and Go installed:

```sh
/usr/bin/python3 packaging/check_flathub.py
```

Results from linter `3.0.0.post897.dev0+c85243b`, checked 2026-10-17:

| Check | Result |
| --- | --- |
| AppStream metadata | Pass |
| Manifest and candidate repository, strict | `finish-args-flatpak-spawn-access` |
| Manifest and candidate repository, permission review | Pass with the same permission warning |

Host execution is still needed for reads, service management, and GNOME shortcut setup. Permission-review mode reports it as a warning; no exception has been granted. Flathub's [submission and AI disclosure rules](https://docs.flathub.org/docs/for-app-authors/requirements) still apply.

The script builds a temporary candidate, mirrors screenshots, and commits `screenshots/x86_64`. Raw results go in `build/flathub-lint/`. It exits nonzero while strict lint fails.

The regular release uses GitHub screenshot URLs. Flathub candidates need its own media hosting, using these builder options:

```sh
--compose-url-policy=full --mirror-screenshots-url=https://dl.flathub.org/media
```

The script creates that media locally; it does not upload it to Flathub. See the [linter rules](https://docs.flathub.org/docs/for-app-authors/linter) for details.
