---
name: sanitized-public-export
description: Publish a private repository as a sanitized public mirror, or hand a project to a third party without leaking personal paths, user names, e-mail addresses, credentials, or private notes. Covers allowlist export, leak scanning with a fixture-aware gate, mirror sync to GitHub, and verification that the published source still builds.
whenToUse: Use when asked to 脱敏发布 / 开源这个项目 / 同步到公开仓库 / 交付源码给外部 / publish this privately-developed project / audit a tree before it leaves the machine. Also use before uploading an archive, attaching a screenshot, or zipping a deliverable.
---

# Sanitized public export

A private working tree is full of things that must never leave it: absolute
paths with a real user name, commit e-mail addresses, cookie values, scratch
notes, build logs, screenshots with metadata. Deleting a few files by hand is
not a control. This procedure replaces hand work with four deterministic steps:

1. **Allowlist** — the published file list comes from `git ls-files` filtered by
   prefixes, so untracked and generated files cannot ride along.
2. **Gate** — a scanner classifies every hit as fixture, retained, or leak, and
   refuses to continue while a leak remains.
3. **Redact** — the replacement half: rewrite secrets and personal data in the
   copy and record what changed.
4. **Mirror** — the exported tree replaces the public checkout wholesale, with a
   neutral commit identity and a verified remote head.

## Pick the smallest path

This is a procedure, not a pipeline. Run only the steps the request needs;
loading the skill never means running all four.

| Situation | Steps | Command |
| --- | --- | --- |
| Sending a zip, screenshot, log, or archive to someone | 2 only, on the extracted copy | `scan.py /tmp/unzipped` |
| Changed README or docs, want a leak check | 2 only, on the repository | `scan.py . --config gate.json` |
| First public release of a private repository | 1 → 2 → 3, then 4 if the project must build from source | `export_allowlist.py`, `scan.py`, `mirror_sync.py` |
| Routine update of an existing public mirror | 3 only (it re-exports and re-scans internally) | `mirror_sync.py --config mirror.json --yes` |
| Shipping a DMG or other binary | 5 only, plus 2 over the install notes | `scan.py` on the DMG staging directory |
| Deciding whether a directory can be published at all | 2 only, JSON output | `scan.py DIR --config gate.json --json` |

A bare "make it public" is not a path choice: ask the publication-mode
question below first.

Escalate only when the input changes shape — a new repository, a new artifact
type, a new directory tree. Re-running an unchanged step adds nothing:

- the gate is read-only and repeatable, but a clean tree stays clean;
- `export_allowlist.py` writes a fresh directory and refuses to overwrite;
- `mirror_sync.py` prints `already matches the export` and exits 0 when nothing changed.

Never run steps 1–3 "for completeness" when the request is only a local audit,
and never publish a mirror without step 2.

Set the toolkit directory once per shell:

    SKILL_DIR=/path/to/Sanitized-Public-Export   # the directory holding this file

## Ask first: which publication mode?

When the request is "公开这个仓库" / "把这个项目开源" / "make this public", stop
and ask before touching anything:

> 公开方式有两种：
> 1. 直接把原仓库的可见性改成 public，保留全部历史；
> 2. 新建一个全新历史的脱敏公开库，原仓库不动。
> 你要哪一种？

If the answer is (1), scan the history, show the findings together with the
risks below, and wait for an explicit confirmation before changing anything:

    git log --all -p | python3 "$SKILL_DIR/scripts/scan.py" /dev/stdin

- the whole history becomes public: absolute paths, scratch documents,
  credentials committed by accident, author e-mail addresses;
- clones, forks, and caches cannot be recalled; switching back to private later
  does not undo them;
- deleted files stay reachable through history and the API;
- every secret must be rotated and the history rewritten (git filter-repo);
  redacting the working tree changes nothing;
- releases, LFS objects, branches, and pull-request discussion become public.

Only after that confirmation run:

    gh repo edit Owner/Name --visibility public --accept-visibility-change-consequences

If the answer is (2) — "不是改原仓库可见性" / "新建" / "镜像" — continue with the
steps below. Never choose a mode on the user's behalf.

## Decide the repository pair first

GitHub refuses two repositories with the same name in one account. If a private
`Owner/Name` already exists, the public mirror needs a different name
(`Name-Public`, `Name-OSS`, plural form). Confirm the target name before creating
anything, then check it does not exist yet:

    gh repo view Owner/Name --json name,visibility 2>/dev/null || echo "name is free"
    gh repo create Owner/Name --public --description "..."

Never delete or rename the private repository to free the name.

## Step 1 — export the allowlist

    python3 "$SKILL_DIR/scripts/export_allowlist.py" --repo ~/src/MyProject --output /tmp/export --include Sources/ --include Resources/ --include scripts/ --include docs/help/ --root-file README.md --root-file .gitignore --root-file Package.swift --rename PUBLIC_README.md=README.md --license-from Resources/ThirdParty/LICENSE.GPLv3 --license-to LICENSE

Symlinks stay links only when their target is exported too: an absolute link is
rewritten relative, and a link pointing outside the repository or at an excluded
file is skipped, so the export never carries bytes the allowlist did not approve.

Rules of thumb:

- Include only source, tests, build scripts, resources, and user documentation.
  Leave out `tools/`, `docs/` internal reports, notes, and anything with a date in the
  name until you have read it.
- Keep a `PUBLIC_README.md` in the private repo and rename it during export, so the
  public README never competes with the private one.
- Copy the licence from the vendored dependency tree; do not retype it.
- Export into a fresh directory every time. `--force` overwrites.

## Step 2 — run the gate

    python3 "$SKILL_DIR/scripts/scan.py" /tmp/export --config gate.json

`gate.json` names your real values so they are searched for literally:

    {
      "literals": ["<your-username>", "<your-email>", "MyProject-Private.git"],
      "detector_files": ["scripts/export-public-source.py"],
      "skip_globs": ["Resources/ThirdParty/**"],
      "allow": []
    }

The gate prints `total / fixture / retained / unexpected` per pattern and exits
non-zero while `unexpected` is above zero. Findings mask every sensitive value on the line, not just the reported one;
`--show-values` prints them verbatim for local work only. Only these count as
fixtures:

- a file listed in `detector_files` (the scanner's own patterns and test data);
- the matched value itself contains a placeholder such as `<user>` or `placeholder`;
- a home-path hit whose next character is not part of a name (`/Users/` alone);
- an address under a reserved domain (`example.com`, `*.invalid`, `*.test`).

### What the gate looks for

| Group | Examples |
| --- | --- |
| Home paths and user names | `/Users/<name>`, `/home/<name>`, `C:\Users\<name>`, a bare user name |
| Contact | e-mail addresses |
| Keys and tokens | PEM private keys, `ghp_` / `github_pat_`, `AKIA`, `aws_secret_access_key`, `xox[baprs]-`, `sk-`, `AIza`, `npm_`, `pypi-`, `dckr_pat_` |
| Session material | JWTs, `Bearer` tokens, `scheme://<user>:<password>@host`, cookie values (`cf_clearance`, `PHPSESSID`, `sessionid`, CSRF tokens) |
| Assignments | `password = ...`, `api_key: ...`, `client_secret = ...`, `token: ...` |

The gate only reports; it never rewrites a file. When the artifact needs the
values replaced rather than reported, run the redaction step below.

Vendor trees are full of upstream authors' addresses; exclude those with
`skip_globs` rather than allowing the whole `email` pattern. Binary payloads are
only checked for credentials and home paths.

A clean gate means no rule matched, not that the tree is safe. Treat `RESULT: clean`
as a precondition: still read the diff and the findings list before publishing.

Fix a leak by editing the source, not by adding an allow rule. Re-run until the
gate prints `RESULT: clean`.

## Keeping a key on purpose

Sometimes the deliverable must ship a working credential so users can run the
project — a demo API key, a sandbox token. Declare it instead of disabling a
whole detector:

    {
      "retain": ["sk-demo-…"]
    }

The gate then reports those hits in a `retained` column and does not fail on them,
`redact.py` leaves them untouched, and every other value is still rewritten. The
report lists what was retained, so the exception is visible rather than silent.

Conditions to state in the same report:

- it is a demo or sandbox credential, scoped to a throwaway account, not a
  production key with billing attached;
- it can be revoked and rotated without breaking real users;
- the README says it is public and rate-limited, so nobody assumes it is a leak;
- everything else — private keys, personal tokens, cookies — is still redacted.

A retained key is a published key. If it cannot be scoped, revoke it and ship a
mock instead.

## Step 2b — rewrite the copy (only when replacement is the right fix)

`scan.py` reports; `redact.py` rewrites. Run it on the exported copy when the
artifact is prose — documentation, transcripts, logs, sample configs — and the
value can be replaced rather than deleted:

    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --dry-run
    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --config gate.json

It rewrites home paths, user names, e-mail addresses, PEM private keys, GitHub /
AWS / Slack / OpenAI / Google / npm / PyPI / Docker tokens, JWTs, bearer tokens,
`scheme://<user>:<password>@host` URLs, cookie values, and `password = …` style
assignments, then prints a per-category count.

On a git checkout it still redacts, and records in the report that history was
not rewritten. Add `--report FILE` for a Markdown summary and
`--check-history` to list the commits that still contain each redacted value:

    python3 "$SKILL_DIR/scripts/redact.py" . --report redaction-report.md --check-history

### Secrets are not a formatting problem

A key or token that reached a commit is compromised: rotate it, and rewrite the
history if the repository will be published. Replacing it with `<token>` only
hides it. For source code, delete the credential and read it from the
environment; keep `redact.py` for the artifact you are about to hand over.

## Step 3 — mirror it

    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --dry-run
    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --yes

`mirror.json`:

    {
      "repo_url": "https://github.com/Owner/Name-Public.git",
      "mirror_dir": "~/src/Name-Public",
      "branch": "main",
      "private_repo": "~/src/MyProject",
      "author": {"name": "Owner", "email": "Owner@users.noreply.github.com"},
      "include": ["Sources/", "Resources/", "scripts/"],
      "root_files": ["README.md", "PUBLIC_README.md", ".gitignore"],
      "renames": {"PUBLIC_README.md": "README.md"},
      "license": {"from": "Resources/ThirdParty/LICENSE.GPLv3", "to": "LICENSE"},
      "gate_config": "gate.json",
      "protect": [".git", ".github"]
    }

The script refuses a dirty private tree (override with `--allow-dirty`), refuses a
public checkout that diverged from or is ahead of its remote (unpublished commits
would otherwise be published), deletes files that are no longer exported, commits with
the configured noreply identity, retries the push three times, and asserts that
`git ls-remote` matches the local head.

## Step 4 — prove the published source still builds

The export must be self-sufficient. Clone it fresh, outside the working tree,
and build with nothing but the repository:

    git clone --depth 1 https://github.com/Owner/Name-Public.git /tmp/fresh
    cd /tmp/fresh && <the documented build command>

If the build needs pinned third-party artifacts, keep the download URLs and
their checksums in the repository (a lock file next to the build script) so a
stranger can reproduce it. Delete `__pycache__` and build directories before
comparing: they embed absolute paths.

## Step 5 — release artifacts

A binary release needs its own pass: sign or ad-hoc sign the bundle, verify
`codesign --verify --deep --strict`, state the minimum OS version, ship a
`SHA256SUMS.txt` next to the archive, and write install notes in every language
the app supports. Never ship the archive from the private build directory
without re-verifying the signature after packaging.

## Hard rules

- A real user name never appears in an artifact — not in source, not in docs,
  not in a commit message, not in a screenshot's metadata. Use `<user>`.
- `~` is not anonymisation when the project name is private. Use `<project dir>`.
- Commit as `Name <Name@users.noreply.github.com>` in the public mirror.
- Do not push the private history to the public remote, not even once. Mirror
  the tree; keep the private history private.
- Check the archive after zipping, not the directory before it: unzip to a
  scratch path and scan that.

## Files in this skill

| Path | Purpose |
| --- | --- |
| `scripts/export_allowlist.py` | git-tracked allowlist export with renames and licence copy |
| `scripts/scan.py` | fixture-aware leak gate over a tree |
| `scripts/redact.py` | rewrite secrets and personal data in an exported copy |
| `scripts/mirror_sync.py` | export + gate + mirror + commit + push + remote assertion |
| `templates/gate.json` | starter gate config |
| `templates/mirror.json` | starter mirror config |
| `references/checklist.md` | pre-publish checklist and real leaks that shipped |

See `references/checklist.md` for the checklist and the leaks that have actually
shipped in practice.
