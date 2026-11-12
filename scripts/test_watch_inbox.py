from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("watch_inbox", Path(__file__).with_name("watch_inbox.py"))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / "MESSAGE_LOG.md"
        self.monitor = watch.Monitor(self.log)
        self.notify = Mock()

    def poll(self):
        self.monitor.poll(self.notify)

    def test_absent_empty_and_header_only_logs_are_silent(self):
        self.poll()
        self.log.write_bytes(b"")
        self.poll()
        self.log.write_bytes(b"# Messages\n")
        self.poll()
        self.notify.assert_not_called()

    def test_existing_backlog_announced_once_until_restart(self):
        self.log.write_bytes(b"- first\n")
        self.poll()
        self.poll()
        self.notify.assert_called_once_with(self.log, 8)
        watch.Monitor(self.log).poll(self.notify)
        self.assertEqual(self.notify.call_count, 2)

    def test_partial_entry_waits_for_newline(self):
        self.log.write_bytes(b"- first")
        self.poll()
        self.notify.assert_not_called()
        self.log.write_bytes(b"- first\n")
        self.poll()
        self.notify.assert_called_once_with(self.log, 8)

    def test_append_batches_one_notice_and_leaves_partial_tail_pending(self):
        self.log.write_bytes(b"- first\n")
        self.poll()
        self.log.write_bytes(b"- first\n- second\n- third\n- fourth")
        self.poll()
        self.poll()
        self.assertEqual(self.notify.call_count, 2)
        self.log.write_bytes(b"- first\n- second\n- third\n- fourth\n")
        self.poll()
        self.assertEqual(self.notify.call_count, 3)

    def test_rewrite_truncation_and_removal_stop_instead_of_losing_work(self):
        for replacement in (b"- other\n", b"", None):
            with self.subTest(replacement=replacement):
                self.log.write_bytes(b"- first\n")
                monitor = watch.Monitor(self.log)
                monitor.poll(self.notify)
                if replacement is None:
                    self.log.unlink()
                else:
                    self.log.write_bytes(replacement)
                with self.assertRaises(watch.LogChanged):
                    monitor.poll(self.notify)

    def test_failed_notification_does_not_advance_progress(self):
        self.log.write_bytes(b"- first\n")
        with self.assertRaises(RuntimeError):
            self.monitor.poll(Mock(side_effect=RuntimeError("delivery failed")))
        self.poll()
        self.notify.assert_called_once_with(self.log, 8)

    def test_explicit_hook_receives_arguments_without_shell_execution(self):
        with patch.object(watch.subprocess, "run") as run, patch("builtins.print"):
            watch.notify(self.log, 8, "/chosen/notify-program")
        run.assert_called_once_with(["/chosen/notify-program", str(self.log), "8"], check=True)

    def test_dead_owner_stops_before_polling(self):
        with patch.object(watch, "owner_alive", return_value=False), patch.object(watch.Monitor, "poll") as poll:
            self.assertEqual(watch.main(["--recipient", "project-one", "--owner-pid", "999999"]), 0)
        poll.assert_not_called()

    def test_intervals_below_thirty_seconds_are_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            watch.main(["--recipient", "project-one", "--interval", "1"])
        self.assertEqual(result.exception.code, 2)

    def test_each_recipient_reads_only_its_own_mailbox(self):
        root = Path(self.directory.name)
        recipients = ("sender-one", "receiver-two", "participant_3")
        for recipient in recipients:
            mailbox = root / "inboxes" / recipient
            mailbox.mkdir(parents=True)
            log = mailbox / "MESSAGE_LOG.md"
            log.write_bytes(f"- for {recipient}\n".encode())
        for recipient in recipients:
            log = root / "inboxes" / recipient / "MESSAGE_LOG.md"
            with patch.object(watch, "notify") as notify:
                self.assertEqual(watch.main(["--once", "--root", str(root), "--recipient", recipient]), 0)
            notify.assert_called_once_with(log.resolve(), len(log.read_bytes()), None)

    def test_recipient_is_required_instead_of_assuming_a_project(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            watch.main(["--once"])
        self.assertEqual(result.exception.code, 2)

    def test_recipient_rejects_path_components_and_nonportable_names(self):
        invalid = ("", "..", "../peer", "/tmp/peer", "a/b", "a\\b", "two words", "UPPER", "-peer", "a" * 65)
        for recipient in invalid:
            with self.subTest(recipient=recipient), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                watch.main(["--once", f"--recipient={recipient}"])
            self.assertEqual(result.exception.code, 2)

    def test_valid_missing_inbox_is_quiet_and_does_not_create_files(self):
        root = Path(self.directory.name)
        with patch.object(watch, "notify") as notify:
            self.assertEqual(watch.main(["--once", "--root", str(root), "--recipient", "new-project"]), 0)
        notify.assert_not_called()
        self.assertEqual(list(root.iterdir()), [])

    def test_notification_failure_exits_nonzero(self):
        root = Path(self.directory.name)
        mailbox = root / "inboxes" / "project-one"
        mailbox.mkdir(parents=True)
        (mailbox / "MESSAGE_LOG.md").write_bytes(b"- message\n")
        with patch.object(watch, "notify", side_effect=RuntimeError("hook failed")), patch("builtins.print"):
            self.assertEqual(watch.main(["--once", "--root", str(root), "--recipient", "project-one"]), 1)

    def test_option_errors_exit_two(self):
        for argv in (["--after", "-1"], ["--once", "--until-notice"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                watch.main(["--recipient", "project-one", *argv])
            self.assertEqual(result.exception.code, 2)

    def test_relocated_install_uses_document_directory_not_working_directory(self):
        root = Path(self.directory.name) / "arbitrary exchange folder"
        scripts = root / "scripts"
        scripts.mkdir(parents=True)
        (root / "COMMUNICATION.md").write_text("# Shared instructions\n")
        installed = scripts / "watch_inbox.py"
        shutil.copyfile(Path(__file__).with_name("watch_inbox.py"), installed)
        log = root / "inboxes" / "custom-id" / "MESSAGE_LOG.md"
        log.parent.mkdir(parents=True)
        log.write_bytes(b"- relocation witness\n")
        result = subprocess.run(
            [sys.executable, "-B", str(installed), "--recipient", "custom-id", "--once"],
            cwd=self.directory.name, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, f"INBOX_CHANGED\t{len(log.read_bytes())}\t{log.resolve()}\n")
        self.assertEqual(result.stderr, "")


class ProcessedPrefixTests(unittest.TestCase):
    """`--after` resumes detection after the bytes the agent has processed, so restarts do not replay them."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / "inboxes" / "project-one" / "MESSAGE_LOG.md"
        self.log.parent.mkdir(parents=True)
        self.first = b"# Messages\n- first\n"
        self.log.write_bytes(self.first)

    def run_main(self, *options, change=None, max_sleeps=3):
        """Run main() with simulated sleeps; the first sleep applies `change`, later ones end the loop."""
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if change and len(sleeps) == 1:
                change()
            if len(sleeps) > max_sleeps:
                raise KeyboardInterrupt

        out, err = io.StringIO(), io.StringIO()
        with patch.object(watch.time, "sleep", side_effect=fake_sleep), patch.object(watch, "owner_alive", return_value=True), redirect_stdout(out), redirect_stderr(err):
            code = watch.main(["--root", str(self.root), "--recipient", "project-one", *options])
        return code, out.getvalue(), err.getvalue(), sleeps

    def notice(self, size):
        return f"INBOX_CHANGED\t{size}\t{self.log.resolve()}\n"

    def test_restart_after_processed_prefix_does_not_replay_it(self):
        self.assertEqual(self.run_main("--once", "--after", str(len(self.first)))[:2], (0, ""))
        self.assertEqual(self.run_main("--once")[:2], (0, self.notice(len(self.first))))

    def test_entries_beyond_processed_prefix_are_announced_at_once(self):
        self.log.write_bytes(self.first + b"- second\n")
        self.assertEqual(self.run_main("--once", "--after", str(len(self.first)))[:2], (0, self.notice(len(self.first) + 9)))

    def test_until_notice_waits_silently_then_exits_after_first_notice(self):
        appended = self.first + b"- second\n"
        code, out, err, sleeps = self.run_main("--until-notice", "--after", str(len(self.first)), change=lambda: self.log.write_bytes(appended))
        self.assertEqual((code, out, err, sleeps), (0, self.notice(len(appended)), "", [30]))

    def test_until_notice_exits_at_once_for_unprocessed_backlog(self):
        self.assertEqual(self.run_main("--until-notice"), (0, self.notice(len(self.first)), "", []))

    def test_until_notice_ignores_unchanged_log_and_partial_entry(self):
        for change in (None, lambda: self.log.write_bytes(self.first + b"- partial")):
            with self.subTest(change=change):
                code, out, err, sleeps = self.run_main("--until-notice", "--after", str(len(self.first)), change=change)
                self.assertEqual((code, out, len(sleeps)), (0, "", 4))

    def test_rewrite_of_processed_prefix_stops_without_notice(self):
        code, out, err, sleeps = self.run_main("--after", str(len(self.first)), change=lambda: self.log.write_bytes(b"# Messages\n- other\n- second\n"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("rewritten or truncated", err)

    def test_processed_prefix_must_be_a_complete_prefix_of_the_log(self):
        for after in (1, len(self.first) + 1):
            with self.subTest(after=after):
                code, out, err, sleeps = self.run_main("--after", str(after))
                self.assertEqual((code, out, sleeps), (1, "", []))
        self.log.unlink()
        code, out, err, sleeps = self.run_main("--once", "--after", "5")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("disappeared", err)

    def test_missing_log_without_processed_bytes_stays_quiet(self):
        self.log.unlink()
        self.assertEqual(self.run_main("--until-notice")[:3], (0, "", ""))


if __name__ == "__main__":
    unittest.main()
