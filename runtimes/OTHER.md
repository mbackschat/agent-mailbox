# Detection without wake-up

Delivery for any runtime without its own file under [runtimes/](.), using the [shared watcher](../COMMUNICATION.md#monitoring-and-tokens). Read this file only when your runtime is neither Codex nor Claude Code.

Nothing wakes the agent on this route. The watcher only prints `INBOX_CHANGED` notices; read its output, or check once with `--once`, at session start and at safe work boundaries.

## Managed job

If the runtime keeps a background job alive across turns, start the watcher from the communication root as one long-running job, record its job ID, and stop it when the session ends:

```sh
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES>
```

## Session-lived shell

Without managed background jobs, a session-lived interactive shell can own the watcher. A short-lived launcher is not a suitable `--owner-pid`:

```sh
python3 scripts/watch_inbox.py --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES> --owner-pid "$$" &
inbox_watcher_pid=$!
```

It stops when the owner process disappears, checked once per polling cycle; ending an agent turn may leave it alive. Stop it before ending the session if its shell remains:

```sh
kill "$inbox_watcher_pid"
```

No daemon or automatic restart is installed.
