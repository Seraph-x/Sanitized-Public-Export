# Credentials: rewrite, retain, or rotate

The gate finds credentials; this page decides what to do with them.

## Three buckets

| Bucket | Example | Action |
| --- | --- | --- |
| Production secret | cloud key, database password, private key | remove and rotate; rewrite history if it was ever committed |
| Needed by the deliverable | sandbox key, test token | replace with a placeholder; hand the real value over a separate channel |
| Deliberately public | demo key, read-only, rate-limited | declare it in `retain` |

## Rewriting a copy

`redact.py` is the replacement half. It works on a checkout as well as on an
exported copy, and it reports what it changed:

    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --dry-run
    python3 "$SKILL_DIR/scripts/redact.py" /tmp/export --report redaction-report.md --check-history

`--check-history` lists the commits that still contain each redacted value
(masked), because rewriting a working tree does not remove a secret from history.
Rotate the value and rewrite the history if the repository is published.

Values are masked in the report; the raw secret never appears in the output.

## Retaining a key on purpose

Declare it instead of disabling a detector:

    {
      "retain": ["sk-demo-…"]
    }

The gate reports those hits in the `retained` column, `redact.py` leaves them
untouched, and everything else is still rewritten.

State the conditions next to the decision:

- it is a demo or sandbox credential, not a production key with billing attached;
- it can be revoked without breaking real users;
- the README says it is public and rate-limited, so nobody mistakes it for a leak.

A retained key is a published key.

## For an internal handoff

Different goal: keep the audit trail. Keep the history, author, tickets and
decision records; remove credentials, personal accounts, absolute paths, local
state, and personal notes. Do not squash history. Record the credential names
and where to request them, never the values.
