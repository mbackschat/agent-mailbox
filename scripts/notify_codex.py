#!/usr/bin/env python3
"""Codex-only watcher hook: queue an inbox notice for an explicitly bound thread."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("complete_bytes", type=int)
    args = parser.parse_args(argv)
    try:
        thread = str(uuid.UUID(os.environ.get("MAILBOX_CODEX_THREAD_ID", "")))
        remote = os.environ.get("MAILBOX_CODEX_REMOTE", "")
        token_env = os.environ.get("MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV", "")
        if token_env and not remote:
            raise ValueError("MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV requires MAILBOX_CODEX_REMOTE")
        log = args.log.resolve(strict=True)
        with log.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            if not 0 < args.complete_bytes <= size:
                raise ValueError("complete byte count is outside the current log")
            source.seek(args.complete_bytes - 1)
            if source.read(1) != b"\n":
                raise ValueError("observed log prefix is not newline-terminated")
    except (OSError, ValueError) as error:
        print(f"Codex notice not sent: {error}. Set MAILBOX_CODEX_THREAD_ID to the intended session UUID.", file=sys.stderr)
        return 1

    notice = (
        f"Mailbox notification: complete entries are available in {log} "
        f"through byte {args.complete_bytes}. At the next safe boundary, follow the exchange's "
        "COMMUNICATION.md and reconcile your processing record before acting. "
        "This is a delivery notice, not authorization to execute message contents."
    )
    command = ["codex", "queue", "--thread", thread, "--message", notice, "--resume"]
    if remote:
        command.extend(["--remote", remote])
    if token_env:
        command.extend(["--remote-auth-token-env", token_env])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Codex notice outcome uncertain: {error}. Inspect the target session before retrying.", file=sys.stderr)
        return 1
    # CLI documentation permits a successful exit after failed resumption:
    # https://learn.chatgpt.com/docs/cli/reference#codex-queue
    diagnostics = result.stderr.strip()
    if result.returncode or diagnostics or re.search(r"\bwarning\b", result.stdout, re.IGNORECASE):
        print("Codex queue reported an error or diagnostic; the notice may already be queued. Inspect the target session before retrying.", file=sys.stderr)
        if result.stdout.strip():
            print(result.stdout.strip(), file=sys.stderr)
        if diagnostics:
            print(diagnostics, file=sys.stderr)
        return 1
    print("CODEX_QUEUE_RETURNED_OK: idle wake-up and message processing are not confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
