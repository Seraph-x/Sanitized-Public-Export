# Exporting the allowlist

`export_allowlist.py` copies only files that git tracks and that match the
include list. Untracked notes, build output, and logs cannot ride along because
they are not in `git ls-files`.

## Command

    python3 "$SKILL_DIR/scripts/export_allowlist.py" --repo ~/src/MyProject --output /tmp/export --include Sources/ --include Resources/ --include scripts/ --include docs/help/ --root-file README.md --root-file .gitignore --root-file Package.swift --rename PUBLIC_README.md=README.md --license-from Resources/ThirdParty/LICENSE.GPLv3 --license-to LICENSE

- `--include` is a path prefix; `--root-file` is an exact name at the repository root.
- `--rename OLD=NEW` rewrites a path, typically to publish `PUBLIC_README.md` as
  `README.md` while the private README stays private.
- `--license-from` copies the licence text from the vendored tree; do not retype it.
- `--manifest` writes the file list and sizes as JSON.
- The output directory must be new or empty; existing targets are never replaced.

## Symlinks

A tracked symlink is not followed blindly:

- target inside the repository and exported → recreated as a relative link;
- target outside the repository, or not part of the export → skipped and listed.

This keeps an absolute path, or a file the allowlist never approved, out of the
export.

## What to leave out

- `tools/`, internal reports, dated documents, meeting notes, screenshots;
- anything you have not read;
- dependency caches and generated files, even if tracked by accident.

## After the export

Run the gate (`references/gate.md`), then either redact
(`references/keys.md`) or fix the source and export again.
