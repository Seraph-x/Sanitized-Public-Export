# Sanitized Public Export

A [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) skill for publishing a private
repository as a sanitized public mirror — without leaking a user name, home
path, e-mail address, credential, or private note.

It is also useful outside DSH: the three scripts are plain Python 3 with no
dependencies and work on any git repository.

## Why

Deleting a few files by hand is not a control. A private tree carries absolute
paths with a real user name, commit e-mail addresses, cookie values, scratch
notes, build logs, and screenshots with metadata. This skill replaces judgement
with three deterministic steps:

| Step | Script | Guarantee |
| --- | --- | --- |
| Allowlist | `scripts/export_allowlist.py` | the file list comes from `git ls-files`, so untracked and generated files cannot ride along |
| Gate | `scripts/scan.py` | every hit is classified as fixture or leak; a single leak stops the pipeline |
| Mirror | `scripts/mirror_sync.py` | the exported tree replaces the public checkout wholesale, committed as a noreply identity, with the remote head verified |

## Install as a DSH skill

User-level (all projects):

    git clone https://github.com/Seraph-x/Sanitized-Public-Export.git \
      ~/.dsh/skills/sanitized-public-export

Project-level (one repository):

    git clone https://github.com/Seraph-x/Sanitized-Public-Export.git \
      .dsh/skills/sanitized-public-export

DSH discovers `SKILL.md` under `<skills root>/<name>/` and reloads it without a
restart.

## Use the scripts directly

    python3 scripts/export_allowlist.py --repo ~/src/MyProject --output /tmp/export \
      --include Sources/ --include scripts/ --root-file README.md \
      --rename PUBLIC_README.md=README.md \
      --license-from Resources/ThirdParty/LICENSE.GPLv3 --license-to LICENSE

    python3 scripts/scan.py /tmp/export --config gate.json

    python3 scripts/mirror_sync.py --config mirror.json --dry-run
    python3 scripts/mirror_sync.py --config mirror.json --yes

`gate.json` lists the real values to search for; `mirror.json` describes the repository
pair. Starter files live in `templates/`. Both are git-ignored by default so personal
values never land in a commit.

## What the gate reports

    pattern                  total  fixture  unexpected
    email                       35        3           0
    posix-home                 221      221           0
    username                   181      181           0
    RESULT: clean

A hit counts as a fixture when the file is a declared detector, the line holds a
placeholder such as `<user>` or `example.com`, a home path is followed by a
non-name character, or the address uses a reserved domain (`example.com`,
`*.invalid`, `*.test`). Everything else is a leak.

## Repository layout

    SKILL.md                     the skill instructions
    scripts/export_allowlist.py  tracked-file allowlist export
    scripts/scan.py              fixture-aware leak gate
    scripts/mirror_sync.py       export + gate + mirror + commit + push
    references/checklist.md      pre-publish checklist and real leaks
    templates/gate.json          starter gate config
    templates/mirror.json        starter mirror config

## Licence

MIT — see [LICENSE](LICENSE).
