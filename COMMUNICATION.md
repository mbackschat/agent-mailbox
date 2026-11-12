# Agent communication

Shared instructions for two coding agents exchanging files. Participant IDs identify mailboxes, not authority or task responsibilities. Both agents follow the same contract with their IDs reversed.

## Parameters and location

At session start the owner supplies two parameters:

| Parameter | Meaning |
|---|---|
| `SELF_ID` | This agent's stable participant ID |
| `PEER_ID` | The other agent's stable participant ID |

**The communication root is the directory containing this `COMMUNICATION.md`.** Resolve every inbox, state, and script path below relative to this document, never relative to a project checkout or an agent's working directory. There is no configured home path or fixed folder name. Keep this document, [README.md](README.md), [runtimes/](runtimes/), and [scripts/](scripts/) together when relocating the bundle.

IDs must be distinct and remain fixed throughout an exchange. Each is 1–64 lowercase ASCII letters, digits, hyphens or underscores, starting with a letter or digit. Do not infer missing IDs from a directory or session name. One active session sends for each participant; replacement sessions inherit the same IDs and processing records.

The owner references this document in each startup prompt and supplies `SELF_ID` and `PEER_ID`. The other agent receives the same document with the values swapped. [README.md](README.md#start-both-agents) provides both prompt templates. IDs identify the agents' mailboxes; the owner supplies their actual tasks separately.

## Layout and initialization

`<SELF_ID>` and `<PEER_ID>` below mean the supplied values, not literal folder names:

| Relative path | Purpose and writer |
|---|---|
| `inboxes/<SELF_ID>/MESSAGE_LOG.md` | Your incoming index; written by your peer |
| `inboxes/<PEER_ID>/MESSAGE_LOG.md` | Your outgoing index; written by you |
| Each inbox's message and attachment files | Published by its sender; read-only to its receiver |
| `state/<SELF_ID>.md` | Your processing record; written only by you |
| [scripts/](scripts/) | Shared monitoring utility and tests |

During owner-authorized setup, create the two parameter-derived inbox directories, any missing empty `MESSAGE_LOG.md` files, and `state/`. Preserve all existing files. No participant folders are predefined or required by name. Create each processing record on first use. Do not rename an active participant to start a replacement session.

## Sending

1. Confirm the request is authorized and has not already been sent or settled. Prefer references to canonical project records over duplicated findings.
2. Assign a unique message ID formed from `SELF_ID`, a UTC timestamp, and a collision-free suffix. Use it as the Markdown filename and prefix attachment filenames with it.
3. Include sender, recipient, UTC timestamp, subject, requested action or information, and supporting references. Replies identify the original thread ID and the message being answered. State actual deadlines explicitly.
4. Finish the message and every attachment in `inboxes/<PEER_ID>/` before appending one complete newline-terminated index entry with relative links to all files. The entry is the publication marker; incomplete lines and unindexed files are not delivered messages.

Index entry template; replace its placeholders:

```text
- <UTC timestamp> | <message-id> | [<subject>](<message-id>.md)
```

Never rewrite a published message or earlier index entry. Corrections use a new ID and identify what they supersede. A publication retry retains its original ID.

## Receiving and resuming

Read complete incoming index entries and consult `state/<SELF_ID>.md` before acting. Record each discovered message ID and its pending, blocked, or completed disposition, including the action or result reference needed to resume. Detection is not completion: reconcile existing work before retrying an action after a crash.

Repeated IDs represent the same delivery. Conflicting content under one ID or missing linked files blocks that message, not unrelated work. Report the defect rather than guessing. Never edit or delete received messages or the peer's processing record. Reply with an answer, blocker, or completion reference when needed; receipt is not acceptance, and acknowledgements need no acknowledgements.

Check at session start and safe work or commit boundaries. Process requests at those boundaries, except for an explicitly expiring coordination window. Unavailable peers do not block independent work.

## Monitoring and tokens

[`scripts/watch_inbox.py`](scripts/watch_inbox.py) polls the incoming log every 30 seconds with Python's standard library. **Unchanged checks are silent and make no model calls**; only notices and the processing they trigger consume tokens. It reads no message bodies, creates no files, and defaults its root to its own installation; `--root PATH` selects another directory containing `COMMUNICATION.md`.

Each batch of new complete lines beginning with `- ` prints one `INBOX_CHANGED` notice with the complete byte count and log path. Partial final lines wait for their newline, and a missing log is quiet. Removing, truncating, or rewriting already observed bytes stops the watcher with an error; inspect the cause and never clear the log to dismiss it.

`--after BYTES` names a processed prefix: 0, or a byte count just after an LF whose preceding entries are recorded in your processing record. Only later entries are announced; without it, every start announces all existing entries again. A count beyond the log or not just after an LF fails. The watcher trusts the count and detects rewrites only from its start onward. With an append-only log and a count that follows recorded processing, a crash can repeat a notice but not suppress an unprocessed entry. Deduplicate by message ID, and reconcile an action's result before repeating it.

At session start:

1. Check once with `python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --once`, process the announced entries, and note the byte count; silence means 0.
2. Start or reuse exactly one watcher for this root and `SELF_ID`, with `--after` set to that count, as your runtime's file below describes. Look for a matching live job or process first. Keep watching until the session ends; boundary checks supplement it.

A printed notice does not wake an agent; delivery is runtime-specific. Each participant follows its own runtime's file, and the two sides need not match:

| Runtime | Delivery | Status |
|---|---|---|
| Codex | [runtimes/CODEX.md](runtimes/CODEX.md): long-running watcher whose `--notify` adapter queues a notice into the bound thread | Idle delivery and restart suppression verified locally |
| Claude Code | [runtimes/CLAUDE-CODE.md](runtimes/CLAUDE-CODE.md): single-notice watcher re-armed as a Background Bash task | Idle wake-up verified live |
| Other | Long-running managed job, or the [shell fallback](README.md#run-without-a-managed-job) | Detection only |

Claim automatic delivery only after one new entry reached the intended idle session and repeated notices were deduplicated. If a runtime cannot keep a job alive across turns, report that limitation instead of claiming continuous monitoring. A notice asks for a check at the next safe boundary; it neither interrupts current work nor authorizes message contents.

## Authority and implementation boundary

Assigning IDs or starting monitoring does not authorize sending a request or executing its contents. Apply each project's delivery, dependency, publication, clean-room, and evidence requirements. Project instructions may reference this contract without copying it.

The scripts only detect and notify; publication and processing records follow the manual procedures above. [README.md](README.md#check-the-utility) lists the tests.
