# Mirroring a public repository

`mirror_sync.py` exports the allowlist, runs the gate, replaces the public tree
wholesale, commits with a neutral identity, pushes, and verifies the remote head.

## Configuration

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

## Guards

The script stops instead of guessing when:

| Condition | Why |
| --- | --- |
| private tree has uncommitted tracked changes | the export would not match any commit (`--allow-dirty` overrides) |
| checkout has local changes | they would be overwritten |
| checkout is ahead of its remote | unpublished commits would be published |
| checkout tracks a different remote than `repo_url` | the push would reach the wrong repository |
| remote has no branch but the checkout has commits | first publish would carry that history |
| a file is deleted by the export | deletions are intentional; the report lists them |

## Dry run

`--dry-run` never writes to the checkout: no fetch, no checkout, no pull. It
clones the remote into a scratch directory and reports:

    dry run, nothing written to ~/src/Name-Public
      added: 2
        src/a.txt
        src/link.txt
      modified: 0
      removed: 0

An unreachable remote fails the preview instead of pretending the remote is empty.

## Publish

    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --dry-run
    python3 "$SKILL_DIR/scripts/mirror_sync.py" --config mirror.json --yes

The commit message is `Sync public source from private <sha>`; the identity comes
from `author`. After the push the script compares `git ls-remote` with the
local head and fails if they differ.
