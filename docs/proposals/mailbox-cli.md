# Proposal: scripted publishing and processing records

Status: proposed 2026-11-13, not implemented. Supersedes the unimplemented `NEXT` wording fix ("record as pending, re-arm, then process").

## Problem

Agents publish messages and maintain processing records by hand:

1. Each disposition update reads and edits `state/<ID>.md`, which grows with every message and implementation checkpoint. Superseded facts remain beside current ones, increasing recovery cost and making the next action ambiguous.
2. Message headers and log lines must be formatted exactly by the model.
3. The processed byte count is copied by hand into `--after`. For Claude Code, the order "record, re-arm, process" depends only on the wording of the `NEXT` line and [runtimes/CLAUDE-CODE.md](../../runtimes/CLAUDE-CODE.md); one agent did process first and re-arm late.

The CLI owns message bookkeeping; a compact recovery snapshot owns current execution context. Routine recovery reads outstanding messages and current work, without loading completed history into model context. The event history may grow on disk; scripts read it without printing it in full.

## Runtime differences

Re-arming is a Claude Code concern. Its runtime wakes an idle session only when a background command exits, so its watcher ends after every notice. Codex and other runtimes keep one long-running watcher, which restarts only at session start or after it stops on an error.

| Runtime | Watcher lifetime | Restart | What this proposal changes |
|---|---|---|---|
| Claude Code | Exits after one notice (`--until-notice`) | After every notice | `TAKE` and `REARM` lines; `--after-state` makes a skipped `take` harmless |
| Codex | Long-running, with the `--notify` adapter | Session start, or after the watcher stops on an adapter failure | The adapter's notice names the `take` command; `--after-state` on every start |
| Other | Long-running, or a session-lived shell | Session start | Boundary checks run `take`; `--after-state` on every start |

All runtimes share one ordering flaw at session start: [COMMUNICATION.md](../../COMMUNICATION.md#monitoring-and-tokens) step 1 processes the announced entries before step 2 starts the watcher, so no watcher runs while startup messages are handled. With this proposal, startup and recovery first read the recovery snapshot, if present, for constraints and process identity. Subject to those constraints, run `take`, start or reuse exactly one watcher with `--after-state` on starts, run `status`, then reconcile and resume. `status` is required because `take` alone does not list previously recorded pending or blocked work. A recorded pause takes precedence over this sequence.

## Design

A new script, `scripts/mailbox.py`, performs message publication and processing-record writes. The agent maintains its recovery snapshot separately. The script's default root is its installation directory, overridable with `--root PATH`, as for `watch_inbox.py`. Every subcommand requires `--self <ID>`; the ID is never inferred.

### Files

| Path | Written by | Format |
|---|---|---|
| `inboxes/<PEER>/<msg-id>.md` | Sender, via `send` | Fixed header block plus body |
| `inboxes/<PEER>/<msg-id>-<name>` | Sender, via `send` | Attachment, copied as is |
| `inboxes/<PEER>/MESSAGE_LOG.md` | Sender, via `send` | Unchanged: `- <UTC> \| <msg-id> \| [<subject>](<msg-id>.md)` |
| `state/<SELF>.jsonl` | Self, via `take` and `mark` | Append-only events; the authoritative processing record |
| `state/<SELF>.md` | Self, by hand | Current recovery snapshot under the contract below; no message ledger or progress journal |
| `state/archive/<SELF>/` | Self, by hand | Optional historical notes linked from the snapshot; never required for routine recovery |

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

### Recovery snapshot

Maintain `state/<SELF>.md` while work or monitoring needs recovery context. Update it at safe work boundaries and before a planned handoff or context compaction. Each concern has one current entry: replace superseded facts rather than appending chronological checkpoints.

An interrupted replacement must leave the previous complete snapshot or the new complete snapshot recoverable; an interrupted initial creation must not expose a partial snapshot as complete. Referenced task/evidence or archive content must be durably recorded before removing its only copy from the snapshot. Reconcile any actions since the last complete checkpoint rather than assuming the snapshot reflects them.

| Content | Contract |
|---|---|
| Current work | Link to the canonical proposal/task table and identify the immediate next action; retain ordering constraints not represented there. |
| Blockers and constraints | Retain unresolved execution blockers, owner instructions affecting resumption, and preservation obligations such as uncommitted user changes. Message dispositions remain in the CLI record. |
| Processes | Record managed session handle, OS PID when known, log/result location, and last observed state for each process still requiring reconciliation, including the watcher and its explicit delivery binding. Handles are recovery hints, not proof of current liveness. |
| Recovery actions | State what to inspect before continuing or retrying; reconcile existing results before repeating work and check live process identity before reuse, replacement, or termination. |
| References | Link to relevant evidence or archives only when needed; keep detailed implementation progress and test evidence in the canonical proposal/task tables. |

Do not copy the inbox offset or a pending/completed message inventory into the snapshot: `status` supplies them. Task links may identify associated message IDs without duplicating dispositions. Remove completed work and reaped processes once their necessary results are recorded in the canonical task/evidence record. Preserve historical context not already recorded elsewhere in linked archives before removing it; archives are consulted only for a specific reconciliation or audit, not read by default.

The snapshot has an 8 KiB (8,192 UTF-8 bytes) soft budget, measured at each checkpoint rather than by line count. Compact an over-budget snapshot by removing superseded facts and moving detail to its canonical record. Never truncate unresolved obligations or hide required recovery actions in an archive to meet the budget. If essential current context still exceeds the budget, retain it and report the size and reason. This is an agent-maintained contract with a size check, not CLI-generated summarization or automatic enforcement.

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

Lists every pending and blocked message with its message path and the latest status event's action/result reference (empty if absent); optional `--all` adds completed ones. References should name the next action, blocker, or canonical result, not carry progress narratives. Output grows with outstanding work, not completed history; no unresolved entries are silently truncated. Read this output together with the recovery snapshot after context compaction or in a new session.

```sh
python3 scripts/mailbox.py status --self web-ui [--all]
# PROCESSED	119
# PENDING	api-server-20261113T103200Z-r2m1	Re: Add GET /health	/abs/inboxes/web-ui/api-server-20261113T103200Z-r2m1.md	"Verify the health badge"
```

The final reference field is a JSON string, so embedded tabs and newlines remain within one output field. An absent reference prints `""`.

### Watcher: `--after-state`

New `watch_inbox.py --after-state`, mutually exclusive with `--after`. At startup it reads the processed count from `state/<recipient>.jsonl`, or 0 if the file is absent. The watcher still writes nothing. This is the core guarantee: a watcher started without a preceding `take` announces the same entries again at once, so "record before re-arm" is enforced by the mechanism, not by wording.

For Claude Code, exit 0 with `--until-notice` prints:

```text
INBOX_CHANGED	119	/abs/inboxes/web-ui/MESSAGE_LOG.md
TAKE	python3 /abs/scripts/mailbox.py --root /abs take --self web-ui
REARM	python3 /abs/scripts/watch_inbox.py --root /abs --recipient web-ui --after-state --until-notice
```

The Claude Code runtime file then says: consult the recovery snapshot and honor its constraints, run `TAKE`, run `REARM` in the background, run `status`, then reconcile and process outstanding work. The `REARM` command is constant per agent. Exit 3 prints only the `REARM` line; the same snapshot constraints apply before re-arming.

For Codex, the [adapter](../../scripts/notify_codex.py) notice names the `take` command, deriving the ID from the log path, instead of asking the agent to reconcile its record by hand. The long-running watcher keeps running, so no re-arm step exists.

### Guarantees

- A log entry appears only after its message and attachments are complete.
- Each message ID is published at most once; a conflicting retry fails without writing.
- A watcher started with `--after-state` announces every entry that `take` has not recorded. Skipping `take` costs an extra wake-up, never a message.
- The record is append-only. A crash leaves at most a partial final line, which `take` and `status` ignore and report.
- The scripts read message headers only, never bodies.
- A peer that publishes by hand stays compatible, because the log entry format is unchanged.
- Default recovery output excludes completed message history; the agent-maintained snapshot preserves all unresolved recovery obligations when compacted.

## Scope

Required:

- `send` with attachments, `take`, `mark`, `status`.
- `watch_inbox.py --after-state` and the `TAKE` and `REARM` output lines.
- Codex adapter notice naming `take`.
- Recovery snapshot contract, including interruption-safe replacement of superseded entries, checkpoint size checks, and preservation of unresolved obligations.
- Documentation rewritten to use the commands; startup and recovery order becomes snapshot/constraints, `take`, watcher, `status`, reconcile/resume:
  - [COMMUNICATION.md](../../COMMUNICATION.md): Layout and initialization, Sending, Receiving and resuming, Monitoring and tokens, and Authority and implementation boundary, which still refers to manual procedures.
  - [README.md](../../README.md): Where messages go, Example session, and Troubleshooting, which replaces the manual `--after` count with `status` and demonstrates snapshot maintenance and recovery; check Reuse or relocate.
  - Runtime files: the cycle in [CLAUDE-CODE.md](../../runtimes/CLAUDE-CODE.md), and the `--after` starts and restarts in [CODEX.md](../../runtimes/CODEX.md) and [OTHER.md](../../runtimes/OTHER.md).

Optional:

- `status --all`.
- Linked snapshot archives for historical context not already retained in canonical task/evidence records.

Excluded:

- Migrating existing `.md` processing records.
- Automatic snapshot generation, summarization, compaction, or event-history rotation.
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
8. With an unchanged outstanding set and offset, adding completed-message history does not change default `status` output. Every pending/blocked entry includes its path and latest reference, including references containing tabs or newlines.
9. Recovery after `take` has recorded work but before processing finishes discovers that work through `status`, even when a subsequent `take` reports no new entries. The snapshot supplies the execution context needed to reconcile rather than repeat actions.
10. A documented checkpoint example replaces stale facts and removes completed work while retaining the current task link, next action, unresolved blocker, process handles, and user-change preservation obligation. Its UTF-8 byte count is checked against 8,192; an over-budget example preserves essential context and reports the overrun instead of truncating it.
11. Recovery consults a snapshot's pause instruction before taking messages or restarting monitoring, and uses its recorded watcher identity and delivery binding when reconciling processes.
12. Interrupting snapshot replacement leaves the previous or new complete snapshot recoverable; initial creation never exposes a partial snapshot as complete. Moving historical detail out of the snapshot preserves its durable destination before removing the source copy.

## Risks

- Agents may keep editing message dispositions by hand. The docs require commands for those writes, and hand edits to `.jsonl` are unsupported; only the recovery snapshot and its optional archives are agent-maintained.
- Snapshot size and freshness depend on agent compliance. The CLI cannot infer missing execution context; a checkpoint size check detects growth, not semantic omissions. A large outstanding workload can also produce large `status` output and must not be silently truncated.
- Writing to a bundle outside the agent's workspace may need sandbox approval, as it does today.
- A single append write is atomic on local filesystems; synced folders such as iCloud or Dropbox do not guarantee it, hence their exclusion.
- Token savings are estimated, not measured: command output scales with new or outstanding work, and the snapshot budget limits routine context growth except for disclosed overruns. Reading the event history still costs script I/O as it grows. Compare one exchange with and without the scripts before quoting numbers.

## Decisions

1. Record format: JSON Lines, recommended. A script-maintained table in `state/<ID>.md` would be easier to read directly, but rewriting Markdown in place is fragile and not crash-safe; `status --all` covers human reading.
2. Manual fallback: keep the message and log formats documented for compatibility and audits; stop documenting manual message-disposition bookkeeping. The recovery snapshot remains agent-maintained. Recommended.
3. The interim `NEXT` fix is replaced by this proposal. Implement it separately only if live Claude Code agents need it before this proposal lands.
4. Recovery context: use a replaceable Markdown snapshot with an 8 KiB soft budget alongside CLI-owned message state. Keep implementation progress in canonical task tables and completed history out of default recovery reads; no separate proposal or migration is required.
