# Sanitized Public Export

A standalone toolkit and agent skill for publishing a private repository as a
sanitized public mirror — without leaking a user name, home path, e-mail
address, credential, or private note.

Four scripts use only the Python standard library; SKILL.md is the procedure an
agent follows. Nothing here depends on a particular agent framework: run the scripts
from a shell, a CI job, a pre-commit hook, or any agent that reads SKILL.md.

## Why

Deleting a few files by hand is not a control. A private tree carries absolute
paths with a real user name, commit e-mail addresses, cookie values, scratch
notes, build logs, and screenshots with metadata. This skill replaces judgement
with four deterministic steps:

| Step | Script | Guarantee |
| --- | --- | --- |
| Allowlist | `scripts/export_allowlist.py` | the file list comes from `git ls-files`, so untracked and generated files cannot ride along |
| Gate | `scripts/scan.py` | every hit is classified as fixture, retained, or leak; a single unexpected leak stops the pipeline |
| Redact | `scripts/redact.py` | rewrites secrets and personal data in a checkout or an exported copy, and reports what changed |
| Mirror | `scripts/mirror_sync.py` | the exported tree replaces the public checkout wholesale, committed as a noreply identity, with the remote head verified |

## Use it

Clone it anywhere:

    git clone https://github.com/Seraph-x/Sanitized-Public-Export.git

From a shell or CI job, call the scripts by path:

    python3 /path/to/Sanitized-Public-Export/scripts/scan.py . --config gate.json

As an agent skill, copy or symlink the repository into whatever directory your
agent scans for skills (the convention is a directory named after the skill that
contains SKILL.md):

    ln -s /path/to/Sanitized-Public-Export ~/.config/<agent>/skills/sanitized-public-export

A pre-commit hook is the same one line:

    python3 /path/to/Sanitized-Public-Export/scripts/scan.py . --config gate.json

## Use the scripts directly

    python3 scripts/export_allowlist.py --repo ~/src/MyProject --output /tmp/export \
      --include Sources/ --include scripts/ --root-file README.md \
      --rename PUBLIC_README.md=README.md \
      --license-from Resources/ThirdParty/LICENSE.GPLv3 --license-to LICENSE

    python3 scripts/scan.py /tmp/export --config gate.json

    python3 scripts/redact.py /tmp/export --dry-run
    python3 scripts/redact.py /tmp/export --config gate.json
    python3 scripts/redact.py /tmp/export --report redaction-report.md --check-history

    python3 scripts/mirror_sync.py --config mirror.json --dry-run
    python3 scripts/mirror_sync.py --config mirror.json --yes

`gate.json` lists the real values to search for; `mirror.json` describes the repository
pair. Starter files live in `templates/`. Both are git-ignored by default so personal
values never land in a commit.

## What the gate reports

    pattern                  total  fixture  retained  unexpected
    email                       35        3         0           0
    posix-home                 221      221         0           0
    username                   181      181         0           0
    RESULT: clean

A hit counts as a fixture when the file is a declared detector, the line holds a
placeholder such as `<user>` or `example.com`, a home path is followed by a
non-name character, or the address uses a reserved domain (`example.com`,
`*.invalid`, `*.test`). Values listed in `gate.json`'s `retain` array count as *retained*: they are
reported, not rewritten, and do not fail the gate. Everything else is a leak.

## Repository layout

    SKILL.md                     the skill instructions
    scripts/export_allowlist.py  tracked-file allowlist export
    scripts/scan.py              fixture-aware leak gate
    scripts/redact.py            rewrite secrets in a checkout or exported copy
    scripts/mirror_sync.py       export + gate + mirror + commit + push
    references/checklist.md      pre-publish checklist and real leaks
    templates/gate.json          starter gate config
    templates/mirror.json        starter mirror config

## Licence

MIT — see [LICENSE](LICENSE).
