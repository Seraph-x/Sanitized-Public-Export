# Pre-publish checklist

Run this before anything leaves the machine: a public repository, a zip, a
screenshot, a pasted log, an archive attached to a message.

## 1. Identity

- [ ] No real user name anywhere: source, docs, comments, config, test data,
      commit messages, file names.
- [ ] No absolute home paths. `/Users/<name>`, `/home/<name>`,
      `C:Users<name>` all count.
- [ ] `~` is not enough when the project name is private:
      `~/Documents/private-project/` still identifies the machine. Use
      `<project dir>`.
- [ ] No e-mail addresses other than the noreply one you commit with.
- [ ] No host names, LAN addresses, or internal service names.

## 2. Credentials

- [ ] No cookie values, session ids, `cf_clearance`, CSRF tokens.
- [ ] No API keys (`ghp_`, `github_pat_`, `AKIA`, `xox[baprs]-`, `sk-`, `AIza`).
- [ ] No `.env`, no private keys, no `state.json` / `cookie.txt` from a real run.
- [ ] Real cookie **names** (not just values) are also fingerprints when they
      carry an account-specific suffix.

## 3. Files that must not travel

- [ ] `__pycache__/`, `.pyc`, `.build/`, `dist/`, `node_modules/`, `.venv/` deleted or
      excluded. A `.pyc` embeds the absolute source path it was compiled from.
- [ ] Internal reports, plans, meeting notes, screenshots, and dated documents
      read before deciding. Default is exclude.
- [ ] Logs and transcripts truncated out, not filtered in.
- [ ] Nothing untracked: the export list must come from `git ls-files`.

## 4. Vendor and licence trees

- [ ] Third-party code ships with its licence text and a source offer where the
      licence requires one.
- [ ] Vendor `CREDITS` / `AUTHORS` files carry upstream addresses — exclude those
      trees from the address scan instead of allowing the whole pattern.
- [ ] Re-distribution status is written down honestly (signed? notarised?
      reviewed by a lawyer?) rather than implied.

## 5. Verify after packaging, not before

- [ ] Unzip the archive to a scratch directory and scan that copy.
- [ ] `strings shot.png | grep /Users/` — screenshots carry metadata.
- [ ] Fresh clone builds from the published source alone.
- [ ] Release asset hash published and re-downloaded once to compare.
- [ ] Public README does not point at the private repository URL.

## Leaks that actually shipped

| What leaked | Where it hid | Why the gate missed it |
|---|---|---|
| `cd ~/Documents/private-project/src` | `NEEDS.md` | `~` was assumed to be anonymisation |
| real cookie name with account suffix | `README.md` ×3 | only values were scanned, not names |
| compiled `.pyc` with `/Users/<name>/...` | `__pycache__/` | directory excluded from the archive, not from the scan |
| table-of-contents anchors built before sanitising | generated markdown | sanitisation ran on body text only, headings kept raw |
| browser path hard-coded for one platform | helper script | not a leak, but the published build could not run elsewhere |

The pattern behind all five: the scan ran on a tree that differed from what was
published, or on fields that the sanitiser did not own. Scan the artifact, and
sanitise the whole document in one pass at the end.
