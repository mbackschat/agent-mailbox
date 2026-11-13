# Codex notification adapter

Codex-only delivery for the [shared watcher](../COMMUNICATION.md#monitoring-and-tokens). Read this file only when your runtime is Codex.

[notify_codex.py](../scripts/notify_codex.py) is the watcher's `--notify` executable. For each notice it runs `codex queue --thread UUID --message NOTICE --resume` ([CLI documentation](https://learn.chatgpt.com/docs/cli/reference#codex-queue)). The notice names the log path and byte count, never message bodies. It uses the existing Codex CLI and adds no Python dependencies.

**Status:** on 2026-11-13, with Codex CLI 0.167.2, a temporary mailbox, and a new throwaway thread, live idle delivery and restart suppression at the processed count were verified. Inside the sandbox the queue call failed; outside it the thread processed the notice without further input, and restarting at the processed count queued nothing over the next polling cycle. Busy-session behavior, remote-server delivery, and crash recovery remain unverified.

## Start

Routine startup requires only the bundled instructions and local CLI checks. Do not invoke documentation skills or browse the web to configure monitoring. If the installed CLI lacks a required capability or the intended thread or server cannot be identified, report the concrete blocker. Research external documentation only when explicitly requested.

Confirm that `codex queue --help` supports `--resume` and identify the intended session UUID. Bind it explicitly; never derive it from `SELF_ID` or use a potentially ambiguous session name. From the communication root, start the single watcher as a long-running managed background job:

```sh
export MAILBOX_CODEX_THREAD_ID='<intended session UUID>'
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES> --notify scripts/notify_codex.py
```

Replace the placeholders; `<PROCESSED_BYTES>` comes from the session-start check. Configuring the adapter sends notices to that session and requires authorization for that delivery.

Record the managed job's execution `session_id` and the watcher's OS PID, and keep its owner alive across turns; a short-lived launcher is not a suitable `--owner-pid`. Check on the watcher through that `session_id` with `write_stdin` or through the PID, not through `/ps` (see [escalated watchers](#escalated-watchers-and-ps)). Stop the identified watcher explicitly when the session ends. Confirm that the CLI can reach the intended server from the watcher's execution environment: a sandbox can block it even when `codex queue --help` succeeds.

`--resume` needs a running local daemon or the server named by `MAILBOX_CODEX_REMOTE`. Optional `MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV` names the environment variable holding that server's token; never put the token itself there.

## Escalated watchers and `/ps`

On macOS with Codex CLI 0.167.2, a controlled test on 2026-11-13 isolated `sandbox_permissions: "require_escalated"` as the trigger for a running command being absent from `/ps`. Commands were launched through `tools.exec_command` inside `functions.exec`, with `yield_time_ms: 1000` and `tty: false`; changing startup output did not affect visibility:

| Launch | With startup output | Silent startup |
|---|---|---|
| Normal sandboxed execution | Visible in `/ps` | Visible in `/ps` |
| `require_escalated` | Missing from `/ps` | Missing from `/ps` |

The missing commands still returned execution session IDs and remained reachable through `write_stdin`. Only commands escalated out of the sandbox are omitted, so an empty `/ps` is not evidence that the watcher failed to start; do not start a duplicate because of it. Whether `/stop` reaches an omitted watcher has not been verified; do not rely on it for cleanup. `/feedback` submits diagnostics and is not a workaround.

| Option | What it provides | Limitation |
|---|---|---|
| Keep the escalated watcher and adapter | Automatic idle delivery was verified; the execution session remains inspectable through `write_stdin` | The watcher is absent from `/ps` |
| Run the watcher sandboxed without `--notify` | Detection inside the sandbox, visible in `/ps` | No automatic Codex wake-up; the agent must check at safe boundaries |

Only the watcher command is escalated; the session needs no Full Access. Moving mailbox files or scripts to `/tmp` does not avoid the escalation: the sandboxed adapter was blocked from the Codex server socket under `~/.codex`, independently of the mailbox location.

## Failures and duplicates

Queueing is attempted once, with a 30-second timeout. A nonzero exit, any stderr, or a stdout warning fails the hook and stops the watcher, because failed resumption can accompany exit code zero. A clean exit establishes only the CLI's reported result, not that the agent woke or processed the notice.

A warning, timeout, or interrupted call may follow a successful queueing. Inspect the target session before restarting the watcher, and never wrap the adapter in a retry loop. Restart with `--after` so processed entries are not queued again; a notice for entries not yet processed can repeat and is deduplicated by message ID.

Tests: `python3 -B scripts/test_notify_codex.py` from the communication root.
