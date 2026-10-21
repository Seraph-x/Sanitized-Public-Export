---
name: sanitized-public-export
description: Publish a private repository as a sanitized public mirror, or hand a project to a third party without leaking personal paths, user names, e-mail addresses, credentials, or private notes. Covers allowlist export, leak scanning with a fixture-aware gate, mirror sync to GitHub, and verification that the published source still builds.
whenToUse: Use when asked to 脱敏发布 / 开源这个项目 / 同步到公开仓库 / 交付源码给外部 / publish this privately-developed project / audit a tree before it leaves the machine. Also use before uploading an archive, attaching a screenshot, or zipping a deliverable.
---

# Sanitized public export

A private tree carries what must not leave it: absolute paths with a real user
name, commit e-mail addresses, credentials, scratch notes, screenshots with
metadata. This procedure replaces hand work with four steps — allowlist, gate,
redact, mirror — and keeps a human at the two irreversible points: changing
visibility, and pushing.

    SKILL_DIR=/path/to/Sanitized-Public-Export   # the directory holding this file

## Pick the smallest path

Run only what the request needs; loading this skill never means running all four.

| Situation | Steps |
| --- | --- |
| Sending a zip, screenshot, log, or archive | gate only, on the extracted copy |
| Changed README or docs, want a check | gate only, on the repository |
| First public release of a private repo | export → gate → (redact) → mirror, then prove the build |
| Routine update of an existing mirror | mirror only (it exports and gates internally) |
| Shipping a DMG or other binary | release checks, plus a gate over the install notes |
| Deciding whether a directory can be published | gate only, `--json` |

## Ask first: which publication mode?

For "公开这个仓库" / "把这个项目开源" / "make this public", stop and ask:

> 公开方式有两种：1）直接把原仓库的可见性改成 public，保留全部历史；
> 2）新建一个全新历史的脱敏公开库，原仓库不动。你要哪一种？

If the answer is (1), scan the history, show the findings and the risks, and
wait for explicit confirmation before running:

    git log --all -p | python3 "$SKILL_DIR/scripts/scan.py" /dev/stdin
    gh repo edit Owner/Name --visibility public --accept-visibility-change-consequences

Risks to state: the whole history becomes public (paths, scratch files,
credentials, author e-mails); clones, forks and caches cannot be recalled;
deleted files stay reachable; every secret must be rotated and the history
rewritten; releases, LFS objects and PR discussion become public too.

If the answer is (2), continue. Never choose a mode on the user's behalf.

## Step 1 — export the allowlist

    python3 "$SKILL_DIR/scripts/export_allowlist.py" --repo ~/src/MyProject --output /tmp/export --include Sources/ --include scripts/ --root-file README.md --rename PUBLIC_README.md=README.md --license-from Resources/ThirdParty/LICENSE.GPLv3 --license-to LICENSE

Only `git ls-files` entries are copied; untracked and generated files cannot
ride along. Symlinks are kept only when their target is exported too. Details:
`references/export.md`.

## Step 2 — run the gate

    python3 "$SKILL_DIR/scripts/scan.py" /tmp/export --config gate.json

Fix leaks by editing the source, not by widening the allowlist. Re-run until it
prints `RESULT: clean`. A clean result means no rule matched, not that the tree
is safe — read the diff and the findings before publishing. Patterns, fixtures,
masking and configuration: `references/gate.md`.

## Step 2b — redact, when replacement is the right fix

    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --dry-run
    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --report redaction-report.md --check-history

For prose — docs, transcripts, logs, sample configs. A secret that reached a
commit must be rotated and the history rewritten; redaction only cleans the
artifact you hand over. Keeping a demo key on purpose, and the internal-handoff
variant: `references/keys.md`.

## Step 3 — mirror it

    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --dry-run
    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --yes

A dry run writes nothing: it previews against a throwaway clone of the remote.
The script refuses a dirty tree, a checkout with local changes, a checkout ahead
of its remote, a checkout tracking another remote, and an empty remote when the
checkout already has history. Configuration and failure modes:
`references/mirror.md`.

## Step 4 — prove the published source still builds

Clone it fresh, outside the working tree, and build with nothing but the
repository:

    git clone --depth 1 https://github.com/Owner/Name-Public.git /tmp/fresh
    cd /tmp/fresh && <the documented build command>

Pinned third-party inputs belong in the repository, with URLs and checksums, so
a stranger can reproduce the build.

## Step 5 — release artifacts

Sign or ad-hoc sign the bundle, verify `codesign --verify --deep --strict`, state
the minimum OS version, ship `SHA256SUMS.txt`, and write install notes in every
language the app supports. Re-verify the signature after packaging.

## Hard rules

- A real user name never appears in an artifact — not in source, not in docs,
  not in a commit message, not in a screenshot's metadata. Use `<user>`.
- `~` is not anonymisation when the project name is private; use `<project dir>`.
- Commit as `Name <Name@users.noreply.github.com>` in the public mirror.
- Never push the private history to the public remote, not even once.
- Check the archive after zipping, not the directory before it.

## Files

| Path | Purpose |
| --- | --- |
| `scripts/export_allowlist.py` | tracked-file allowlist export |
| `scripts/scan.py` | fixture-aware leak gate |
| `scripts/redact.py` | rewrite secrets, with a report |
| `scripts/mirror_sync.py` | export + gate + mirror + push |
| `references/gate.md` | patterns, fixtures, masking, config |
| `references/export.md` | allowlist rules and symlink policy |
| `references/keys.md` | rewrite, retain, rotate; internal handoff |
| `references/mirror.md` | mirror config, guards, dry run |
| `references/checklist.md` | pre-publish checklist and real leaks |
