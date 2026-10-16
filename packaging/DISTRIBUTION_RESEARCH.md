# Repository distribution findings

Checked 2026-10-16 against Flatpak documentation, GitHub documentation, and GNOME Software 50.4 source. These are implementation recommendations, not claims that a deployment or installer test has already succeeded.

## Recommended installer

Publish a signed OSTree repository under GitHub Pages and make a `.flatpakref` the primary download. Flatpak explicitly supports Pages hosting; installing a reference adds the repository and allows subsequent `flatpak update` operations. Publish a `.flatpakrepo` separately for users wanting to add the whole remote. Both reference formats should embed the signing **public** key encoded as one base64 line. Keep the private signing key outside Git and published artifacts. [Flatpak hosting](https://docs.flatpak.org/en/latest/hosting-a-repository.html), [reference format](https://docs.flatpak.org/en/latest/repositories.html#flatpakref-files)

Suggested layout, with `OWNER` replaced by the authenticated account:

```text
https://OWNER.github.io/victus-fan-control/
  index.html
  .nojekyll
  fan-control.flatpakref
  fan-control.flatpakrepo
  signing-key.gpg
  repo/config
  repo/summary
  repo/summary.sig
  repo/objects/...
  repo/refs/...
```

The reference's `Url` must point at `.../repo/`, not the project homepage. Include `Name`, `Branch=stable`, `IsRuntime=false`, `SuggestRemoteName=victus-fan-control`, `Title`, `Comment`, `Description`, `Homepage`, `Icon`, `RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo`, and `GPGKey`. The repository descriptor uses `[Flatpak Repo]`, `Url`, `Title`, `Homepage`, `Comment`, `Description`, `Icon`, and `GPGKey`. [Flatpak formats](https://docs.flatpak.org/en/latest/hosting-a-repository.html#flatpakrepo-files)

## Export and signing

Run these against the finalized staging directory; the positional order is **repository, application directory, branch**:

```sh
flatpak build-export \
  --collection-id=io.github.OWNER.VictusFanControl.Repository \
  --gpg-sign="$SIGNING_FINGERPRINT" --gpg-homedir="$SIGNING_DIRECTORY" \
  public/repo STAGED_APP stable

flatpak build-update-repo \
  --gpg-sign="$SIGNING_FINGERPRINT" --gpg-homedir="$SIGNING_DIRECTORY" \
  --title='Fan Control' --default-branch=stable \
  --homepage='https://github.com/OWNER/victus-fan-control' \
  --generate-static-deltas public/repo
```

Sign commits and summary. AppStream regeneration is enabled by default. Reuse the signing identity and collection ID; `--deploy-collection-id` permanently propagates that ID. Preserve repository history; `--prune --prune-depth=N` controls retention. Flags were checked against installed command help. Static deltas improve downloads. [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-build-export), [hosting performance](https://docs.flatpak.org/en/latest/hosting-a-repository.html#important-details)

A secondary `.flatpak` can include `--repo-url=https://OWNER.github.io/victus-fan-control/repo/ --gpg-keys=PUBLIC_KEY_FILE` when built. Prefer the reference for GNOME Software's complete initial page. [Bundle command](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-build-bundle)

## GitHub Pages publishing

Publish the complete static tree without modifying binary OSTree objects. A source-branch deployment should contain root `.nojekyll` to bypass Jekyll and an `index.html` entry page. Actions deployment needs `pages: write`, `id-token: write`, a `github-pages` environment, and dependency ordering between upload and deployment. [Site setup](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site), [custom workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

If using `actions/upload-pages-artifact`, explicitly set `include-hidden-files: true` so `.nojekyll` is retained. Its tar step dereferences symbolic and hard links, as required for Pages artifacts. Pin the action version/commit and check that version's inputs. [Action implementation](https://github.com/actions/upload-pages-artifact/blob/main/action.yml)

Pages allows published sites up to 1 GB and has a soft 100 GB/month bandwidth limit. This is suitable for the existing small Python app repository; monitor growth and move hosting if needed. [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

## Metadata and GNOME Software

Keep `project_license=MIT`, the actual MIT license file, developer, releases, and stock icon. Add real `homepage`, `vcs-browser`, and `bugtracker` URLs. Add light/dark screenshots with direct HTTPS image URLs such as `https://raw.githubusercontent.com/OWNER/victus-fan-control/COMMIT/data/screenshots/fan-control-light.png`. Commit the images first, then pin their commit in MetaInfo; Flathub recommends tags/commits rather than moving branches. Validate source MetaInfo and inspect the **generated repository AppStream catalog**, since this is what the installer consumes. [MetaInfo guidelines](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines#screenshots)

GNOME Software 50.4 treats the formats differently:

- Bundle import refines embedded AppStream using only `GS_PLUGIN_REFINE_REQUIRE_FLAGS_ID` (around line 4006).
- Reference import adds the remote to a **temporary** installation and aborts before installation (around 4200), obtains remote sizes, sets `LOCAL_HAS_REPOSITORY`, loads remote AppStream, then refines using `GS_PLUGIN_REFINE_REQUIRE_FLAGS_MASK` (around 4400).

This supports the inference that repository references fix the missing license, repository, and size presentation. Confirm with the actual installed GNOME Software version before claiming success. [GNOME Software 50.4 source](https://github.com/GNOME/gnome-software/blob/50.4/plugins/flatpak/gs-flatpak.c#L4082)

The host-command permission still legitimately produces a security warning. Metadata, screenshots, signing, and repository hosting do not remove that capability. Keep it disclosed rather than falsifying safety metadata. [Flatpak sandbox guidance](https://docs.flatpak.org/en/latest/sandbox-permissions.html#d-bus-access)

## Validate without permanent installation

Use a temporary per-user installation; `FLATPAK_USER_DIR` overrides its directory. Restrict every command to `--user`:

```sh
validation_directory=$(mktemp -d)
export FLATPAK_USER_DIR="$validation_directory/flatpak"
flatpak remote-add --user fan-control https://OWNER.github.io/victus-fan-control/fan-control.flatpakrepo
flatpak update --user --appstream fan-control
flatpak remote-info --user fan-control APP_ID//stable
flatpak remote-ls --user --app fan-control
```

Run in a child process. These commands inspect metadata without installing the app or changing normal installations. [Flatpak environment and commands](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak)

Finally open the published `.flatpakref` in GNOME Software and verify icon, screenshots, MIT, links, version, sizes, and repository notice. Its source explicitly performs preview resolution in a temporary installation; do not click Install during this check. Fetch the public `summary`, `summary.sig`, referenced screenshots, and icon separately to detect Pages 404s. [GNOME Software preview implementation](https://github.com/GNOME/gnome-software/blob/50.4/plugins/flatpak/gs-flatpak.c#L4200)
