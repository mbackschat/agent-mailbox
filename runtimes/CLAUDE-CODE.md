# Claude Code single-notice watcher

Claude Code-only delivery for the [shared watcher](../COMMUNICATION.md#monitoring-and-tokens). Read this file only when your runtime is Claude Code.

Claude Code wakes an idle session when a [background command](https://code.claude.com/docs/en/tools-reference#background-commands) exits, not when it prints. In interactive local sessions such commands have no time limit and stop when the session ends. Claude Code therefore re-arms a watcher that exits after one notice, instead of keeping one running. No `--notify` hook is involved.

**Status:** idle wake-up verified live with Claude Code 2.1.323 on 2026-11-13 against a temporary mailbox. Busy-session delivery remains unverified.

## Cycle

1. After the session-start check, confirm no watcher for this communication root and `SELF_ID` is running, for example with `pgrep -fl watch_inbox.py`. Claude Code's wrapper shell repeats the arguments, so one watcher can appear twice.
2. Start it with Background Bash (`run_in_background`), using absolute paths so its arguments identify the root and ID. Replace the placeholders:

   ```sh
   python3 "<ROOT>/scripts/watch_inbox.py" --root "<ROOT>" --recipient "${SELF_ID:?Set SELF_ID}" --after <PROCESSED_BYTES> --until-notice
   ```

3. Its completion notice wakes the session. It does not ask you to stop current work. At the next safe boundary, read the task output. Exit 0 always carries one `INBOX_CHANGED` notice: record the entries through its byte count in your processing record, then re-arm with that count. Entries published before re-arming make the new watcher exit at once, so none are lost.
4. Exit 3 means it stopped without a notice because its owner exited or it was interrupted; re-arm with the previous count. Exit 1 reports an inaccessible, removed, rewritten, or truncated log, or an invalid processed count, on stderr; inspect the cause before re-arming. Exit 2 reports invalid arguments. Stopping the task yourself ends it by signal.

Polling uses no model tokens; each exit costs one turn.

## Limits

- Claude Code does not restore background commands on `--resume`; re-arm at session start.
- Two watchers for the same root and ID cause duplicate wake-ups, not duplicate processing, provided the processing record is consulted.
- Unattended runs (`-p`, Agent SDK, cloud) give background commands a time limit, so the watcher ends early and needs re-arming.
- Claude Code may stop background tasks under critical memory pressure once the session has been idle for 30 minutes ([background Bash commands](https://code.claude.com/docs/en/interactive-mode#background-bash-commands)); re-arm from the last processed count.
