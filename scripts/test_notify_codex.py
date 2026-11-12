from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("notify_codex", Path(__file__).with_name("notify_codex.py"))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "inboxes" / "arbitrary-id" / "MESSAGE_LOG.md"
        self.log.parent.mkdir(parents=True)
        self.log.write_bytes(b"- a complete entry\n")
        self.thread = "01234567-89ab-4cde-8012-3456789abcde"
        self.env = {"MAILBOX_CODEX_THREAD_ID": self.thread}

    def invoke(self, result=None, env=None):
        result = result or subprocess.CompletedProcess([], 0, "Queued\n", "")
        with patch.dict(os.environ, self.env if env is None else env, clear=True), patch.object(adapter.subprocess, "run", return_value=result) as run, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = adapter.main([str(self.log), str(self.log.stat().st_size)])
        return code, run

    def test_queues_only_a_notice_to_the_explicit_thread(self):
        code, run = self.invoke()
        self.assertEqual(code, 0)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["codex", "queue", "--thread", self.thread])
        self.assertIn("--resume", args)
        notice = args[args.index("--message") + 1]
        self.assertIn(str(self.log), notice)
        self.assertIn("safe boundary", notice)
        self.assertNotIn("a complete entry", notice)
        self.assertEqual(run.call_args.kwargs, {"capture_output": True, "text": True, "timeout": 30})

    def test_missing_or_named_thread_is_rejected_without_invoking_codex(self):
        for env in ({}, {"MAILBOX_CODEX_THREAD_ID": "friendly-session-name"}):
            with self.subTest(env=env):
                code, run = self.invoke(env=env)
                self.assertNotEqual(code, 0)
                run.assert_not_called()

    def test_remote_endpoint_and_token_variable_name_are_explicit(self):
        env = dict(self.env, MAILBOX_CODEX_REMOTE="unix:///tmp/example.sock", MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV="EXAMPLE_AUTH")
        code, run = self.invoke(env=env)
        self.assertEqual(code, 0)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--remote") + 1], env["MAILBOX_CODEX_REMOTE"])
        self.assertEqual(args[args.index("--remote-auth-token-env") + 1], "EXAMPLE_AUTH")

    def test_auth_variable_without_remote_is_rejected(self):
        code, run = self.invoke(env=dict(self.env, MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV="EXAMPLE_AUTH"))
        self.assertNotEqual(code, 0)
        run.assert_not_called()

    def test_resume_warning_with_zero_exit_is_not_silent_success(self):
        for stdout, stderr in (("Queued", "Warning: failed to resume"), ("WARNING: resume failed", ""), ("", "unexpected diagnostic")):
            with self.subTest(stdout=stdout, stderr=stderr):
                code, run = self.invoke(subprocess.CompletedProcess([], 0, stdout, stderr))
                self.assertNotEqual(code, 0)
                run.assert_called_once()

    def test_queue_error_is_reported_without_retry(self):
        code, run = self.invoke(subprocess.CompletedProcess([], 1, "", "Queue failed"))
        self.assertNotEqual(code, 0)
        run.assert_called_once()

    def test_timeout_or_missing_cli_is_reported_without_retry(self):
        for error in (FileNotFoundError("codex missing"), subprocess.TimeoutExpired("codex", 30)):
            with self.subTest(error=error), patch.dict(os.environ, self.env, clear=True), patch.object(adapter.subprocess, "run", side_effect=error) as run, redirect_stderr(io.StringIO()):
                self.assertNotEqual(adapter.main([str(self.log), str(self.log.stat().st_size)]), 0)
                run.assert_called_once()

    def test_incomplete_or_out_of_range_prefix_never_queues(self):
        for size in (0, 1, self.log.stat().st_size + 1):
            with self.subTest(size=size), patch.dict(os.environ, self.env, clear=True), patch.object(adapter.subprocess, "run") as run, redirect_stderr(io.StringIO()):
                self.assertNotEqual(adapter.main([str(self.log), str(size)]), 0)
                run.assert_not_called()

    def test_watcher_and_executable_adapter_with_simulated_cli(self):
        root = Path(self.temp.name)
        hook = root / "notify_codex.py"
        shutil.copyfile(Path(__file__).with_name("notify_codex.py"), hook)
        hook.chmod(0o755)
        fake = root / "codex"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['TEST_ARGUMENTS']).write_text(json.dumps(sys.argv[1:]))\n"
            "if os.environ.get('TEST_WARNING'):\n"
            "    print('Warning: unable to resume', file=sys.stderr)\n"
        )
        fake.chmod(0o755)
        record = root / "arguments.json"
        env = dict(os.environ, **self.env, TEST_ARGUMENTS=str(record), PATH=str(root) + os.pathsep + os.environ.get("PATH", os.defpath))
        env.pop("MAILBOX_CODEX_REMOTE", None)
        env.pop("MAILBOX_CODEX_REMOTE_AUTH_TOKEN_ENV", None)
        command = [sys.executable, "-B", str(Path(__file__).with_name("watch_inbox.py")), "--root", str(root), "--recipient", "arbitrary-id", "--once", "--notify", str(hook)]
        for warning in (False, True):
            with self.subTest(warning=warning):
                env["TEST_WARNING"] = "yes" if warning else ""
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1 if warning else 0)
                self.assertEqual(json.loads(record.read_text())[:3], ["queue", "--thread", self.thread])
                if warning:
                    self.assertIn("may already be queued", result.stderr)
                    self.assertNotIn("INBOX_CHANGED", result.stdout)
                else:
                    self.assertIn("INBOX_CHANGED", result.stdout)

    def test_restart_after_processed_prefix_queues_nothing(self):
        root = Path(self.temp.name)
        fake = root / "codex"
        record = root / "arguments.json"
        fake.write_text(f"#!{sys.executable}\nimport pathlib\npathlib.Path({str(record)!r}).write_text('called')\n")
        fake.chmod(0o755)
        env = dict(os.environ, **self.env, PATH=str(root) + os.pathsep + os.environ.get("PATH", os.defpath))
        command = [sys.executable, "-B", str(Path(__file__).with_name("watch_inbox.py")), "--root", str(root), "--recipient", "arbitrary-id",
                   "--once", "--after", str(self.log.stat().st_size), "--notify", str(Path(__file__).with_name("notify_codex.py"))]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertFalse(record.exists())


if __name__ == "__main__":
    unittest.main()
