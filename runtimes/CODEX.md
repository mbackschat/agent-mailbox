# Codex notification adapter

Codex-only delivery for the [shared watcher](../COMMUNICATION.md#monitoring-and-tokens). Read this file only when your runtime is Codex.

[notify_codex.py](../scripts/notify_codex.py) is the watcher's `--notify` executable. For each notice it runs `codex queue --thread UUID --message NOTICE --resume` ([CLI documentation](https://learn.chatgpt.com/docs/cli/reference#codex-queue)). The notice names the log path and byte count, never message bodies. It uses the existing Codex CLI and adds no Python dependencies.

**Status:** on 2026-11-13, with Codex CLI 0.167.2, a temporary mailbox, and a new throwaway thread, live idle delivery and restart suppression at the processed count were verified. Inside the sandbox the queue call failed; outside it the thread processed the notice without further input, and restarting at the processed count queued nothing over the next polling cycle. Busy-session behavior, remote-server delivery, and crash recovery remain unverified.

## Start

Confirm that `codex queue --help` supports `--resume` and identify the intended session UUID. Bind it explicitly; never derive it from `SELF_ID` or use a potentially ambiguous session name. From the communication root, start the single watcher as a long-running managed background job:

```sh
export MAILBOX_CODEX_THREAD_ID='<intended session UUID>'
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES> --notify scripts/notify_codex.py
```

Replace the placeholders; `<PROCESSED_BYTES>` comes from the session-start check. Configuring the adapter sends notices to that session and requires authorization for that delivery.

Record the managed job ID and keep its owner alive across turns; a short-lived launcher is not a suitable `--owner-pid`. Stop the watcher when the session ends. Confirm that the CLI can reach the intended server from the watcher's execution environment: a sandbox can block it even when `codex queue --help` succeeds.

`--resume` needs a running local daemon or the server named by `MAILBOX_CODEX_REMOTE`. Optional `MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV` names the environment variable holding that server's token; never put the token itself there.

## Failures and duplicates

Queueing is attempted once, with a 30-second timeout. A nonzero exit, any stderr, or a stdout warning fails the hook and stops the watcher, because failed resumption can accompany exit code zero. A clean exit establishes only the CLI's reported result, not that the agent woke or processed the notice.

A warning, timeout, or interrupted call may follow a successful queueing. Inspect the target session before restarting the watcher, and never wrap the adapter in a retry loop. Restart with `--after` so processed entries are not queued again; a notice for entries not yet processed can repeat and is deduplicated by message ID.

Tests: `python3 -B scripts/test_notify_codex.py` from the communication root.
