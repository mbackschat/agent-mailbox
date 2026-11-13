#!/usr/bin/env python3
"""Notice complete inbox log entries without invoking a model or reading payloads."""

import argparse
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


class LogChanged(RuntimeError):
    """Previously observed complete log bytes were removed or rewritten."""


class Monitor:
    def __init__(self, log):
        self.log = log
        self.observed = b""

    def skip(self, processed):
        """Treat the first `processed` bytes as observed; they must be a complete-entry prefix of the log."""
        if processed == 0:
            return
        try:
            data = self.log.read_bytes()
        except FileNotFoundError:
            raise LogChanged(f"Processed log disappeared: {self.log}")
        if len(data) < processed or data[processed - 1:processed] != b"\n":
            raise LogChanged(f"Processed prefix of {processed} bytes is not a complete-entry prefix of {self.log}")
        self.observed = data[:processed]

    def poll(self, deliver):
        try:
            data = self.log.read_bytes()
        except FileNotFoundError:
            if self.observed:
                raise LogChanged(f"Observed log disappeared: {self.log}")
            return
        if not data.startswith(self.observed):
            raise LogChanged(f"Append-only log was rewritten or truncated: {self.log}")
        complete = data[:data.rfind(b"\n") + 1]
        added = complete[len(self.observed):]
        # Split on LF only, like the completeness and --after checks: splitlines() would also
        # break at a bare CR and announce "- " text inside a non-entry line.
        if any(line.startswith(b"- ") for line in added.split(b"\n")):
            deliver(self.log, len(complete))
        # Commit detection progress only after delivery succeeds; restarting replays it.
        self.observed = complete


def notify(log, complete_bytes, hook=None):
    if hook:
        subprocess.run([hook, str(log), str(complete_bytes)], check=True)
    print(f"INBOX_CHANGED\t{complete_bytes}\t{log}", flush=True)


def rearm_command(root, recipient, after):
    """Return the command that starts the next single-notice watcher after `after` processed bytes.

    Single-notice watchers end by design, and nothing restarts them; printing the exact command in the
    exit output keeps the re-arm step in front of an agent whose context lost the runtime instructions.
    The owner PID is omitted because the next launch has a different parent.
    """
    script = Path(__file__).resolve()
    return shlex.join(["python3", str(script), "--root", str(root), "--recipient", recipient, "--after", str(after), "--until-notice"])


def owner_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def participant_id(value):
    """Accept one portable mailbox name, never a path or an inferred identity."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise argparse.ArgumentTypeError("participant ID must be 1–64 lowercase ASCII letters, digits, hyphens or underscores, starting with a letter or digit")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", type=participant_id, required=True, help="Your participant ID; reads inboxes/ID/MESSAGE_LOG.md")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--interval", type=float, default=30, help="Seconds between checks, minimum 30")
    parser.add_argument("--owner-pid", type=int, default=os.getppid(), help="Stop when this process exits; default: parent")
    parser.add_argument("--after", type=int, default=0, help="Complete byte count already processed; only later entries are announced")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Check once, announcing complete entries beyond --after")
    mode.add_argument("--until-notice", action="store_true", help="Exit 0 after the first notice, for runtimes woken by job exit; exit 3 if stopped without one")
    parser.add_argument("--notify", type=Path, help="Optional executable called with log path and complete byte count")
    args = parser.parse_args(argv)
    if args.after < 0:
        parser.error("--after must not be negative")
    if not math.isfinite(args.interval) or args.interval < 30:
        parser.error("--interval must be finite and at least 30 seconds")
    if args.owner_pid <= 0:
        parser.error("--owner-pid must be positive")
    hook = str(args.notify.resolve()) if args.notify else None
    if hook and (not Path(hook).is_file() or not os.access(hook, os.X_OK)):
        parser.error("--notify must name an executable file")
    root = args.root.resolve()
    monitor = Monitor(root / "inboxes" / args.recipient / "MESSAGE_LOG.md")
    delivered = None

    def deliver(log, size):
        nonlocal delivered
        notify(log, size, hook)
        delivered = size

    try:
        monitor.skip(args.after)
        while args.once or owner_alive(args.owner_pid):
            monitor.poll(deliver)
            if args.once or (args.until_notice and delivered is not None):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Watcher stopped: {error}", file=sys.stderr)
        return 1
    # A job-exit wake-up must not look like delivery when the owner vanished or the wait was interrupted.
    if args.until_notice and delivered is None:
        print("Watcher stopped without a notice: owner exited or interrupted", file=sys.stderr)
        print(f"REARM\t{rearm_command(root, args.recipient, args.after)}", file=sys.stderr)
        return 3
    if args.until_notice:
        state = root / "state" / f"{args.recipient}.md"
        print(f"NEXT\tRecord these entries in {state}, then re-arm in the background with:\t{rearm_command(root, args.recipient, delivered)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
