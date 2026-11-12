# Shared mailboxes for coding agents

Use this bundle to exchange Markdown messages and attachments between two coding agents. Choose their participant IDs at startup; no project or participant is built in. The polling script makes no model calls.

[COMMUNICATION.md](COMMUNICATION.md) owns the communication rules. **Its containing directory is the shared root.** All `inboxes/`, `state/`, and `scripts/` paths are relative to that document, regardless of either agent's working directory.

## Start both agents

Choose two different stable IDs, called `<FIRST_ID>` and `<SECOND_ID>` in the templates below. Use lowercase ASCII letters, digits, hyphens or underscores, with a letter or digit first; maximum 64 characters. These are mailbox identities, not task assignments. Give each agent its task separately.

Replace every angle-bracketed placeholder before sending the prompts. `<DOCUMENT_REFERENCE>` must locate the same existing `COMMUNICATION.md` for both agents: provide a file link or a path each agent can resolve. Relative references may differ between their working directories; both must resolve to the same document. Do not provide a separate exchange-root setting.

**Prompt for the first agent:**

```text
Read and follow <DOCUMENT_REFERENCE> (COMMUNICATION.md).
SELF_ID: <FIRST_ID>
PEER_ID: <SECOND_ID>
Use the directory containing that document as the communication root.
Resolve inboxes, state, and scripts relative to that document.
Initialize missing inboxes for these IDs and empty message logs without
overwriting existing contents; create state/ if absent.
Start or reuse exactly one watcher for SELF_ID as required by Monitoring
and tokens and your runtime's file under runtimes/; keep watching until the
session ends.
Check your inbox now and at safe work boundaries. Consult your processing
record before acting. Apply your project's authorization and evidence rules.
```

**Prompt for the second agent:**

```text
Read and follow <DOCUMENT_REFERENCE> (COMMUNICATION.md).
SELF_ID: <SECOND_ID>
PEER_ID: <FIRST_ID>
Use the directory containing that document as the communication root.
Resolve inboxes, state, and scripts relative to that document.
Initialize missing inboxes for these IDs and empty message logs without
overwriting existing contents; create state/ if absent.
Start or reuse exactly one watcher for SELF_ID as required by Monitoring
and tokens and your runtime's file under runtimes/; keep watching until the
session ends.
Check your inbox now and at safe work boundaries. Consult your processing
record before acting. Apply your project's authorization and evidence rules.
```

Keep one active sending session per ID. A replacement session receives the same prompt and resumes from its existing processing record. ID assignment alone does not grant permission to send a restricted request.

## Where messages go

Each agent interprets these paths using its own parameters:

| Action | Path relative to COMMUNICATION.md |
|---|---|
| Read incoming messages | `inboxes/<SELF_ID>/MESSAGE_LOG.md` |
| Publish messages to the peer | `inboxes/<PEER_ID>/` and its `MESSAGE_LOG.md` |
| Record processing progress | `state/<SELF_ID>.md` |

The inbox folder names come entirely from the supplied IDs. There are no preset participant directories to rename. Setup creates missing directories and empty logs; each agent creates its processing record on first use.

Once delivery is authorized, ask an agent to send its request under the [sending procedure](COMMUNICATION.md#sending). It finishes the message and attachments in the peer's inbox before appending their links to the log. The receiving agent reads them at a safe boundary, records its disposition, and publishes any needed reply through the other inbox. Publishing messages and maintaining processing records are agent tasks, not watcher features.

## Check or monitor an inbox

Python 3 is required; no additional packages are needed. From the directory containing `COMMUNICATION.md`, with `SELF_ID` set to the value supplied to that agent, check once:

```sh
SELF_ID='<your supplied participant ID>'
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --once
```

`INBOX_CHANGED` reports new complete entries and the log's complete byte count. Silence can mean an empty, unchanged, or missing inbox; check the ID and setup if a message was expected. Pass that count as `--after` to later starts so processed entries are not announced again. Stop a foreground watcher with **Ctrl-C**.

Continuous monitoring and agent wake-up depend on the runtime: [Codex](runtimes/CODEX.md) queues a notice through `--notify`; [Claude Code](runtimes/CLAUDE-CODE.md) re-arms a single-notice watcher, whose idle wake-up is live-verified. [The monitoring contract](COMMUNICATION.md#monitoring-and-tokens) covers the shared rules. **Polling uses no model tokens**; notices and message processing can.

If the watcher reports a rewritten, truncated, or removed log, inspect the cause before restarting. Do not clear the log to dismiss the error.

## Run without a managed job

When the runtime offers no managed background jobs, a session-lived interactive shell can own the watcher. A short-lived launcher is not a suitable `--owner-pid`:

```sh
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES> --owner-pid "$$" &
inbox_watcher_pid=$!
```

It stops when the owner process disappears, checked once per polling cycle; ending an agent turn may leave it alive. Stop it before ending the session if its shell remains:

```sh
kill "$inbox_watcher_pid"
```

No daemon or automatic restart is installed. This route only detects; it does not wake the agent.

## Reuse or relocate

For a new exchange, copy only this README, [COMMUNICATION.md](COMMUNICATION.md), [runtimes/](runtimes/), and [scripts/](scripts/) to any shared directory. Supply the new document reference and two chosen IDs in the prompts. The agents create the matching inboxes; no source edits are required. Keep old messages and processing records with their original exchange.

To relocate an existing exchange, stop its watchers and move the whole bundle, including inboxes and state. Update each agent's document reference, keep its IDs unchanged, and start or reuse one watcher per active participant. The watcher's default root follows its installation, not the caller's working directory. `--root PATH` can select the directory containing a different `COMMUNICATION.md` when necessary.

## Check the utility

From the document's directory:

```sh
python3 -B scripts/test_watch_inbox.py
python3 -B scripts/test_notify_codex.py
python3 scripts/watch_inbox.py --help
```

Tests use temporary mailboxes and include routing after relocation.
