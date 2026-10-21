# The gate, in detail

`scan.py` reports; it never rewrites. Run it on the export (or on any tree
about to leave your control) and read the table.

## Output

    pattern                  total  fixture  retained  unexpected
    email                       35        3         0           0
    posix-home                 221      221         0           0
    username                   181      181         0           0
    RESULT: clean

- `fixture` — documentation, a detector's own pattern, or a placeholder; not
  counted against you.
- `retained` — declared in `gate.json`'s `retain` array; reported, not
  rewritten, does not fail the gate.
- `unexpected` — a leak. Non-zero exit status.

Findings mask every sensitive value on the reported line, including the user name
inside a home path. `--show-values` prints them verbatim; use it only locally.

## What counts as a fixture

- the file is listed in `detector_files` (the scanner's own source and tests);
- the matched value itself is a placeholder: an exact token, a bracketed name, a
  shell variable, or a placeholder word such as `example` / `dummy` / `redacted`;
- an address uses a reserved domain (`example.com`, `*.invalid`, `*.test`,
  `users.noreply.github.com`);
- a home path whose name is itself a placeholder (`/Users/<name>`).

A token that merely contains `dummy` is still a leak.

## What it looks for

| Group | Examples |
| --- | --- |
| Home paths | `/Users/<name>`, `/home/<name>`, `C:Users<name>` |
| Contact | e-mail addresses |
| Keys and tokens | PEM private keys, `ghp_` / `github_pat_`, `AKIA`, `aws_secret_access_key`, `xox[baprs]-`, `sk-`, `AIza`, `npm_`, `pypi-`, `dckr_pat_` |
| Session material | JWTs, `Bearer` tokens, `scheme://<user>:<password>@host`, cookie values (`cf_clearance`, `PHPSESSID`, `sessionid`, CSRF) |
| Assignments | `password = ...`, `api_key: ...`, `client_secret = ...`, `token: ...` |

Vendor trees are full of upstream authors' addresses; exclude them with `skip_globs`
instead of allowing the whole `email` pattern. Binary files are only checked for
credentials and home paths.

## Configuration

    {
      "literals": ["<your-username>", "<your-email>", "MyProject-Private.git"],
      "detector_files": ["scripts/export-public-source.py"],
      "skip_globs": ["Resources/ThirdParty/**"],
      "retain": [],
      "allow": []
    }

`allow` disables a whole pattern — prefer fixing the source. `retain` keeps
specific values, see `references/keys.md`.

## The limit

A clean gate means no rule matched, not that the tree is safe. Treat it as a
precondition: read the diff and the findings before publishing.
