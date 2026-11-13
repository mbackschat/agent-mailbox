# Shared mailboxes for coding agents

Use this bundle to exchange Markdown messages and attachments between two coding agents. **It works with any coding agent system that can read and write files and run Python 3:** messages are plain files, and the contract is one Markdown document each agent follows. The two agents may run on different systems.

Automatic wake-up comes from a small runtime file per system, currently [Codex](runtimes/CODEX.md) and [Claude Code](runtimes/CLAUDE-CODE.md). Any other system still detects messages through the same watcher and inbox checks, as [runtimes/OTHER.md](runtimes/OTHER.md) describes. Supporting its wake-up means adding a runtime file, an adapter script if needed, and a row in the [runtime table](COMMUNICATION.md#monitoring-and-tokens); message format and procedures stay unchanged.

Choose the participant IDs at startup; no project or participant is built in. The polling script makes no model calls.

[COMMUNICATION.md](COMMUNICATION.md) owns the communication rules. **Its containing directory is the shared root.** All `inboxes/`, `state/`, and `scripts/` paths are relative to that document, regardless of either agent's working directory.

## Start both agents

Choose two different stable IDs, called `<FIRST_ID>` and `<SECOND_ID>` in the templates below. Use lowercase ASCII letters, digits, hyphens or underscores, with a letter or digit first; maximum 64 characters. These are mailbox identities, not task assignments. Give each agent its task separately.

Replace every angle-bracketed placeholder before sending the prompts. `<COMMUNICATION_PATH>` is the absolute path of this bundle's `COMMUNICATION.md`, identical in both prompts, for example `/Users/dev/agent-mailbox/COMMUNICATION.md`. Avoid relative paths: each agent resolves them against its own working directory, so the same text can reach different files. Do not provide a separate exchange-root setting; the root is the directory of that file.

**Prompt for the first agent:**

```text
Read and follow <COMMUNICATION_PATH>.
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
Read and follow <COMMUNICATION_PATH>.
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

## Example session

A Claude Code agent works on a web UI in `~/work/web`, and a Codex agent works on its API in `~/work/api`. The bundle is cloned to `/Users/dev/agent-mailbox`, outside both projects.

**1. Start.** Send each agent its filled-in prompt. To the Claude Code agent:

```text
Read and follow /Users/dev/agent-mailbox/COMMUNICATION.md.
SELF_ID: web-ui
PEER_ID: api-server
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

To the Codex agent:

```text
Read and follow /Users/dev/agent-mailbox/COMMUNICATION.md.
SELF_ID: api-server
PEER_ID: web-ui
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

Each agent creates `inboxes/web-ui/MESSAGE_LOG.md`, `inboxes/api-server/MESSAGE_LOG.md`, and `state/` if missing, checks once (silent, so 0 bytes processed), and starts its watcher. Claude Code runs a background `--until-notice` watcher for `web-ui`; Codex runs a long-running watcher for `api-server` with the `--notify` adapter.

**2. Send.** You tell the Claude Code agent: "Ask api-server for a `GET /health` endpoint." That authorizes the delivery. It writes `inboxes/api-server/web-ui-20261113T101500Z-k3p9.md`:

```markdown
# Add GET /health

- Message ID: `web-ui-20261113T101500Z-k3p9`
- From: `web-ui`
- To: `api-server`
- Sent: 2026-11-13T10:15:00Z

Please add `GET /health` returning `200 {"status":"ok"}`; the UI's status badge polls it. Reply with the commit once it is merged.
```

Only then does it append the publication marker to `inboxes/api-server/MESSAGE_LOG.md`:

```text
- 2026-11-13T10:15:00Z | web-ui-20261113T101500Z-k3p9 | [Add GET /health](web-ui-20261113T101500Z-k3p9.md)
```

**3. Receive and reply.** Within 30 seconds the `api-server` watcher prints `INBOX_CHANGED` with 107 bytes, and the adapter queues that notice into the Codex thread. At its next safe boundary Codex reads the message, records it as pending in `state/api-server.md`, implements the endpoint, and updates the record:

```markdown
| Message ID | Disposition | Action or result reference |
|---|---|---|
| web-ui-20261113T101500Z-k3p9 | completed | Commit `4f2a9c1`; reply `api-server-20261113T103200Z-r2m1` |
```

It publishes the reply the same way: first `inboxes/web-ui/api-server-20261113T103200Z-r2m1.md`, naming `web-ui-20261113T101500Z-k3p9` as its thread and the message it answers, then this entry in `inboxes/web-ui/MESSAGE_LOG.md`:

```text
- 2026-11-13T10:32:00Z | api-server-20261113T103200Z-r2m1 | [Re: Add GET /health](api-server-20261113T103200Z-r2m1.md)
```

**4. Wake up and re-arm.** The `web-ui` watcher exits, which wakes the idle Claude Code session. Its output carries the notice and the next command:

```text
INBOX_CHANGED	119	/Users/dev/agent-mailbox/inboxes/web-ui/MESSAGE_LOG.md
NEXT	Record these entries in /Users/dev/agent-mailbox/state/web-ui.md, then re-arm in the background with:	python3 /Users/dev/agent-mailbox/scripts/watch_inbox.py --root /Users/dev/agent-mailbox --recipient web-ui --after 119 --until-notice
```

The Claude Code agent reads the reply, records it in `state/web-ui.md`, and runs that command in the background. The reply needs no acknowledgement, so the exchange ends here. The bundle now holds:

```text
agent-mailbox/
├── COMMUNICATION.md
├── inboxes/
│   ├── api-server/
│   │   ├── MESSAGE_LOG.md
│   │   └── web-ui-20261113T101500Z-k3p9.md
│   └── web-ui/
│       ├── MESSAGE_LOG.md
│       └── api-server-20261113T103200Z-r2m1.md
└── state/
    ├── api-server.md
    └── web-ui.md
```

## Troubleshooting

To see whether messages are waiting for an agent, run from the directory containing `COMMUNICATION.md`:

```sh
python3 scripts/watch_inbox.py --recipient <ID> --after <PROCESSED_BYTES> --once
```

Take `<PROCESSED_BYTES>` from that agent's processing record, `state/<ID>.md`; without `--after`, every entry is announced again. `INBOX_CHANGED` with a byte count means unprocessed entries are waiting. Silence means none: the log may be missing, empty, header-only, or end in a partial entry. Check the ID and setup if a message was expected.

- If a watcher reports a rewritten, truncated, or removed log, inspect the cause before restarting it. Never clear the log to dismiss the error.
- On Codex, the watcher that wakes the agent runs escalated out of the sandbox and is therefore absent from `/ps`; see [escalated watchers](runtimes/CODEX.md#escalated-watchers-and-ps).

## Reuse or relocate

For a new exchange, clone this repository, or copy only this README, [COMMUNICATION.md](COMMUNICATION.md), [runtimes/](runtimes/), and [scripts/](scripts/) to any shared directory. In a clone, `.gitignore` keeps `inboxes/` and `state/` out of version control. Supply the new absolute path of its `COMMUNICATION.md` and two chosen IDs in the prompts. The agents create the matching inboxes; no source edits are required. Keep old messages and processing records with their original exchange.

To relocate an existing exchange, stop its watchers and move the whole bundle, including inboxes and state. Update the `COMMUNICATION.md` path in each agent's prompt, keep its IDs unchanged, and start or reuse one watcher per active participant. The watcher's default root follows its installation, not the caller's working directory. `--root PATH` can select the directory containing a different `COMMUNICATION.md` when necessary.

## Check the utility

From the document's directory:

```sh
python3 -B scripts/test_watch_inbox.py
python3 -B scripts/test_notify_codex.py
python3 scripts/watch_inbox.py --help
```

Tests use temporary mailboxes and include routing after relocation.

## License

[MIT](LICENSE)
