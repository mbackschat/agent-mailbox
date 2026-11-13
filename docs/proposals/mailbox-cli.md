# Proposal: scripted publishing and processing records

Status: proposed 2026-11-13, not implemented. Supersedes the unimplemented `NEXT` wording fix ("record as pending, re-arm, then process").

## Problem

Agents publish messages and maintain processing records by hand:

1. Each disposition update reads and edits `state/<ID>.md`, which grows with every message.
2. Message headers and log lines must be formatted exactly by the model.
3. The processed byte count is copied by hand into `--after`. For Claude Code, the order "record, re-arm, process" depends only on the wording of the `NEXT` line and [runtimes/CLAUDE-CODE.md](../../runtimes/CLAUDE-CODE.md); one agent did process first and re-arm late.

Token savings are a secondary benefit. Per message they are modest; they grow with history, because today's record and log reads load every earlier entry. The main benefit is that the rules move into code.

## Runtime differences

Re-arming is a Claude Code concern. Its runtime wakes an idle session only when a background command exits, so its watcher ends after every notice. Codex and other runtimes keep one long-running watcher, which restarts only at session start or after it stops on an error.

| Runtime | Watcher lifetime | Restart | What this proposal changes |
|---|---|---|---|
| Claude Code | Exits after one notice (`--until-notice`) | After every notice | `TAKE` and `REARM` lines; `--after-state` makes a skipped `take` harmless |
| Codex | Long-running, with the `--notify` adapter | Session start, or after the watcher stops on an adapter failure | The adapter's notice names the `take` command; `--after-state` on every start |
| Other | Long-running, or a session-lived shell | Session start | Boundary checks run `take`; `--after-state` on every start |

All runtimes share one ordering flaw at session start: [COMMUNICATION.md](../../COMMUNICATION.md#monitoring-and-tokens) step 1 processes the announced entries before step 2 starts the watcher, so no watcher runs while startup messages are handled. With this proposal, startup becomes: `take`, start the watcher with `--after-state`, then process.

## Design

A new script, `scripts/mailbox.py`, performs every write. Its default root is its installation directory, overridable with `--root PATH`, as for `watch_inbox.py`. Every subcommand requires `--self <ID>`; the ID is never inferred.

### Files

| Path | Written by | Format |
|---|---|---|
| `inboxes/<PEER>/<msg-id>.md` | Sender, via `send` | Fixed header block plus body |
| `inboxes/<PEER>/<msg-id>-<name>` | Sender, via `send` | Attachment, copied as is |
| `inboxes/<PEER>/MESSAGE_LOG.md` | Sender, via `send` | Unchanged: `- <UTC> \| <msg-id> \| [<subject>](<msg-id>.md)` |
| `state/<SELF>.jsonl` | Self, via `take` and `mark` | Append-only events; the authoritative processing record |
| `state/<SELF>.md` | Self, by hand | Optional free-form notes, no longer part of the contract |

Fixed message header; "In reply to" and "Attachments" appear only when they apply:

```markdown
# Add GET /health

- Message ID: `web-ui-20261113T101500Z-k3p9`
- From: `web-ui`
- To: `api-server`
- Sent: 2026-11-13T10:15:00Z
- Thread: `web-ui-20261113T101500Z-k3p9`
- In reply to: `api-server-20261113T090000Z-a1b2`
- Attachments: [web-ui-20261113T101500Z-k3p9-spec.md](web-ui-20261113T101500Z-k3p9-spec.md)

<body>
```

State events, one JSON object per line:

```json
{"at":"2026-11-13T10:32:05Z","event":"take","through":119}
{"at":"2026-11-13T10:32:05Z","event":"status","id":"api-server-20261113T103200Z-r2m1","status":"pending"}
{"at":"2026-11-13T10:41:10Z","event":"status","id":"api-server-20261113T103200Z-r2m1","status":"completed","ref":"Commit 4f2a9c1"}
```

The latest `status` event for an ID wins. The processed count is the largest `through` value, or 0 if there is none. JSON Lines rather than TSV, because result references are free text and JSON escapes tabs and newlines.

### `send`

Publishes one message; the body comes from standard input:

```sh
python3 scripts/mailbox.py send --self web-ui --to api-server --subject "Add GET /health" \
  [--reply-to <msg-id>] [--thread <msg-id>] [--attach FILE ...] [--id <msg-id>] < body.md
# SENT	web-ui-20261113T101500Z-k3p9	/abs/inboxes/api-server/web-ui-20261113T101500Z-k3p9.md
```

- ID: built from `SELF`, the UTC time, and a random 4-character suffix.
- Write order: attachments first, then the message through a temporary file renamed into place, then the log line in a single append write.
- Thread: a reply uses the thread named in the replied-to message's header; otherwise the message starts its own thread. `--thread` overrides this when a manually written message has no header.
- Retry: `--id` naming an already published message with identical content succeeds without writing. Different content exits 1 and writes nothing.

### `take`

Records new entries as pending and lists them:

```sh
python3 scripts/mailbox.py take --self web-ui
# NEW	api-server-20261113T103200Z-r2m1	Re: Add GET /health	/abs/inboxes/web-ui/api-server-20261113T103200Z-r2m1.md
# THROUGH	119
```

- Reads up to the log's last complete line, so the agent never handles byte counts; entries that arrived after the notice are taken too.
- Appends a `pending` event for each entry not yet recorded, plus one `take` event.
- A malformed entry is recorded as `blocked` and listed as `MALFORMED`; an entry whose linked file is missing is recorded as `blocked` and listed as `BLOCKED`.
- Without new entries it prints only `THROUGH`.

### `mark`

Sets one message's disposition to `pending`, `blocked`, or `completed`. An ID that `take` never recorded exits 1.

```sh
python3 scripts/mailbox.py mark --self web-ui --id api-server-20261113T103200Z-r2m1 --status completed --ref "Commit 4f2a9c1"
```

### `status`

Lists pending and blocked messages; `--all` adds completed ones. This is the cheap way to resume after context compaction or in a new session.

```sh
python3 scripts/mailbox.py status --self web-ui [--all]
# PROCESSED	119
# PENDING	api-server-20261113T103200Z-r2m1	Re: Add GET /health
```

### Watcher: `--after-state`

New `watch_inbox.py --after-state`, mutually exclusive with `--after`. At startup it reads the processed count from `state/<recipient>.jsonl`, or 0 if the file is absent. The watcher still writes nothing. This is the core guarantee: a watcher started without a preceding `take` announces the same entries again at once, so "record before re-arm" is enforced by the mechanism, not by wording.

For Claude Code, exit 0 with `--until-notice` prints:

```text
INBOX_CHANGED	119	/abs/inboxes/web-ui/MESSAGE_LOG.md
TAKE	python3 /abs/scripts/mailbox.py --root /abs take --self web-ui
REARM	python3 /abs/scripts/watch_inbox.py --root /abs --recipient web-ui --after-state --until-notice
```

The Claude Code runtime file then says: run `TAKE`, run `REARM` in the background, then process the listed messages. The `REARM` command is constant per agent. Exit 3 prints only the `REARM` line.

For Codex, the [adapter](../../scripts/notify_codex.py) notice names the `take` command, deriving the ID from the log path, instead of asking the agent to reconcile its record by hand. The long-running watcher keeps running, so no re-arm step exists.

### Guarantees

- A log entry appears only after its message and attachments are complete.
- Each message ID is published at most once; a conflicting retry fails without writing.
- A watcher started with `--after-state` announces every entry that `take` has not recorded. Skipping `take` costs an extra wake-up, never a message.
- The record is append-only. A crash leaves at most a partial final line, which `take` and `status` ignore and report.
- The scripts read message headers only, never bodies.
- A peer that publishes by hand stays compatible, because the log entry format is unchanged.

## Scope

Required:

- `send` with attachments, `take`, `mark`, `status`.
- `watch_inbox.py --after-state` and the `TAKE` and `REARM` output lines.
- Codex adapter notice naming `take`.
- Documentation rewritten to use the commands; startup order becomes `take`, watcher, process:
  - [COMMUNICATION.md](../../COMMUNICATION.md): Layout and initialization, Sending, Receiving and resuming, Monitoring and tokens, and Authority and implementation boundary, which still refers to manual procedures.
  - [README.md](../../README.md): Where messages go, Example session, and Troubleshooting, which replaces the manual `--after` count with `status`; check Reuse or relocate.
  - Runtime files: the cycle in [CLAUDE-CODE.md](../../runtimes/CLAUDE-CODE.md), and the `--after` starts and restarts in [CODEX.md](../../runtimes/CODEX.md) and [OTHER.md](../../runtimes/OTHER.md).

Optional:

- `status --all`.

Excluded:

- Migrating existing `.md` processing records; existing exchanges stay on the manual procedure.
- Reading or summarizing bodies, authorization decisions, automatic processing.
- Several sessions writing for one ID; the contract already allows one active session per ID.
- Ensuring a Claude Code watcher runs at all. `--after-state` makes a skipped `take` harmless only once `REARM` runs; if the agent never runs it, or a session resumes or compacts after the watcher exited, no watcher exists and nothing prints. Only a Claude Code hook would enforce this: a `SessionStart` hook (startup, resume, compact) that reports a missing watcher, or a `Stop` hook that blocks ending a turn without one. Both need per-project setup and are left for a separate decision.
- Windows, network filesystems, and cloud-synced folders.

## Acceptance criteria

1. An interrupted `send` leaves no log entry.
2. An identical `send` retry writes nothing; a conflicting retry exits 1 and changes nothing.
3. `take` lists only unrecorded entries, records them as pending, flags malformed entries and missing files, and ignores a partial final record line.
4. With `--after-state`, the watcher waits silently after `take`, exits at once with the same entries without `take`, and starts from 0 without a record file.
5. The Codex adapter's notice names the correct `take` command for the log's recipient.
6. The README example session runs entirely through the commands, and its printed output matches the README.
7. Routing works after relocation, as the current watcher tests already check.

## Risks

- Agents may keep editing by hand. The docs describe only the commands, and hand edits to `.jsonl` are documented as unsupported.
- Writing to a bundle outside the agent's workspace may need sandbox approval, as it does today.
- A single append write is atomic on local filesystems; synced folders such as iCloud or Dropbox do not guarantee it, hence their exclusion.
- Token savings are estimated, not measured: `send` takes one call instead of two or three; `take`, `mark`, and `status` print a fixed amount instead of re-reading growing files; `COMMUNICATION.md` gets shorter. Compare one exchange with and without the scripts before quoting numbers.

## Decisions

1. Record format: JSON Lines, recommended. A script-maintained table in `state/<ID>.md` would be easier to read directly, but rewriting Markdown in place is fragile and not crash-safe; `status --all` covers human reading.
2. Manual fallback: keep the message and log formats documented for compatibility and audits; stop documenting manual record-keeping. Recommended.
3. The interim `NEXT` fix is replaced by this proposal. Implement it separately only if live Claude Code agents need it before this proposal lands.
