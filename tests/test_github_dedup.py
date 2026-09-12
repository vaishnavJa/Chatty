import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from chatty.integrations.github.dedup import CallLedger

PAYLOAD = {"name": "create_issue", "arguments": {"title": "Fixture", "body": ""}}
RESULT = {
    "ok": True,
    "repository": "vaishnavJa/Chatty",
    "data": {"number": 7, "url": "https://github.com/vaishnavJa/Chatty/issues/7"},
}


class CallLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "calls.sqlite"

    def test_reopened_ledger_returns_saved_result_without_running_operation(self):
        self.assertEqual(
            CallLedger(self.path).run("session", "call", PAYLOAD, lambda: RESULT),
            RESULT,
        )
        result = CallLedger(self.path).run(
            "session", "call", PAYLOAD, lambda: self.fail("duplicate write")
        )
        self.assertEqual(result, RESULT)


class FailureAndConcurrencyTests(CallLedgerTests):
    def test_conflicting_payload_is_rejected(self):
        ledger = CallLedger(self.path)
        ledger.run("s", "c", PAYLOAD, lambda: RESULT)
        result = ledger.run("s", "c", {"name": "different"}, lambda: self.fail("write"))
        self.assertEqual(result["error"]["code"], "call_conflict")

    def test_callback_exception_is_sanitized_and_cached(self):
        def operation():
            raise RuntimeError("secret-token")

        first = CallLedger(self.path).run("s", "c", PAYLOAD, operation)
        second = CallLedger(self.path).run(
            "s", "c", PAYLOAD, lambda: self.fail("write")
        )
        self.assertEqual(first, second)
        self.assertTrue(first["error"]["uncertain"])
        self.assertNotIn("secret-token", str(first))

    def test_error_envelopes_are_cached(self):
        failure = {
            "ok": False,
            "error": {
                "code": "timeout",
                "message": "Unknown outcome",
                "uncertain": True,
            },
        }
        CallLedger(self.path).run("s", "c", PAYLOAD, lambda: failure)
        self.assertEqual(
            CallLedger(self.path).run("s", "c", PAYLOAD, lambda: self.fail("write")),
            failure,
        )

    def test_invalid_ids_and_payload_do_not_execute(self):
        ledger = CallLedger(self.path)
        for value in (None, 1, True, "", "  ", "a" * 257):
            for session, call in ((value, "c"), ("s", value)):
                with self.subTest(session=session, call=call):
                    result = ledger.run(
                        session, call, PAYLOAD, lambda: self.fail("write")
                    )
                    self.assertEqual(result["error"]["code"], "invalid_arguments")
        for payload in ([], {"value": object()}, {"value": float("nan")}):
            with self.subTest(payload=payload):
                result = ledger.run("s", "c", payload, lambda: self.fail("write"))
                self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_storage_failure_prevents_operation(self):
        self.path.write_bytes(b"not a database")
        operation = Mock(return_value=RESULT)
        result = CallLedger(self.path).run("s", "c", PAYLOAD, operation)
        self.assertEqual(result["error"]["code"], "ledger_storage_error")
        self.assertTrue(result["error"]["uncertain"])
        operation.assert_not_called()

    def assert_unavailable_replay_is_uncertain(self):
        operation = Mock(return_value=RESULT)
        with patch(
            "sqlite3.connect",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            result = CallLedger(self.path).run("s", "c", PAYLOAD, operation)
        operation.assert_not_called()
        self.assertEqual(result["error"]["code"], "ledger_storage_error")
        self.assertTrue(result["error"]["uncertain"])
        self.assertIn("Do not retry with a new call ID", result["error"]["message"])
        self.assertNotIn("database is locked", result["error"]["message"])

    def test_inaccessible_completed_call_preserves_uncertainty(self):
        timeout = {
            "ok": False,
            "error": {
                "code": "timeout",
                "message": "Unknown outcome",
                "uncertain": True,
            },
        }
        for envelope in (RESULT, timeout):
            with self.subTest(envelope=envelope):
                if self.path.exists():
                    self.path.unlink()
                self.assertEqual(
                    CallLedger(self.path).run(
                        "s", "c", PAYLOAD, Mock(return_value=envelope)
                    ),
                    envelope,
                )
                self.assert_unavailable_replay_is_uncertain()

    def test_inaccessible_pending_call_preserves_uncertainty(self):
        def interrupted():
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            CallLedger(self.path).run("s", "c", PAYLOAD, interrupted)
        self.assert_unavailable_replay_is_uncertain()
        operation = Mock(return_value=RESULT)
        result = CallLedger(self.path).run("s", "c", PAYLOAD, operation)
        self.assertEqual(result["error"]["code"], "call_pending")
        operation.assert_not_called()

    def test_in_memory_storage_is_rejected(self):
        result = CallLedger(":memory:").run(
            "s", "c", PAYLOAD, lambda: self.fail("write")
        )
        self.assertEqual(result["error"]["code"], "ledger_storage_error")

    def test_failed_result_save_leaves_durable_pending(self):
        def operation():
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(
                    "CREATE TRIGGER deny_update BEFORE UPDATE ON github_calls BEGIN SELECT RAISE(ABORT, fixture); END"
                )
            return RESULT

        first = CallLedger(self.path).run("s", "c", PAYLOAD, operation)
        self.assertEqual(first["error"]["code"], "ledger_storage_error")
        self.assertTrue(first["error"]["uncertain"])
        repeated = CallLedger(self.path).run(
            "s", "c", PAYLOAD, lambda: self.fail("write")
        )
        self.assertEqual(repeated["error"]["code"], "call_pending")

    def test_reservation_is_committed_before_callback_and_other_calls_can_run(self):
        def operation():
            ledger = CallLedger(self.path)
            duplicate = ledger.run("s", "c", PAYLOAD, lambda: self.fail("duplicate"))
            self.assertEqual(duplicate["error"]["code"], "call_pending")
            self.assertTrue(duplicate["error"]["uncertain"])
            return ledger.run("s", "another", PAYLOAD, lambda: RESULT)

        self.assertEqual(
            CallLedger(self.path).run("s", "c", PAYLOAD, operation), RESULT
        )

    def test_process_death_leaves_pending_across_restart(self):
        import multiprocessing

        process = multiprocessing.get_context("spawn").Process(
            target=crash_after_reservation, args=(str(self.path),)
        )
        process.start()
        process.join(15)
        self.assertEqual(process.exitcode, 23)
        result = CallLedger(self.path).run(
            "s", "c", PAYLOAD, lambda: self.fail("write")
        )
        self.assertEqual(result["error"]["code"], "call_pending")
        self.assertTrue(result["error"]["uncertain"])

    def test_concurrent_processes_execute_once(self):
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        start = context.Event()
        queue = context.Queue()
        marker = Path(self.directory.name) / "effects"
        processes = [
            context.Process(
                target=concurrent_call, args=(str(self.path), str(marker), start, queue)
            )
            for _ in range(4)
        ]
        for process in processes:
            process.start()
        start.set()
        results = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(15)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(marker.read_text(), "write\n")
        self.assertTrue(any(result == RESULT for result in results))
        self.assertTrue(
            all(
                result == RESULT or result["error"]["code"] == "call_pending"
                for result in results
            )
        )


def crash_after_reservation(path):
    import os

    CallLedger(path).run("s", "c", PAYLOAD, lambda: os._exit(23))


def concurrent_call(path, marker, start, queue):
    def operation():
        with open(marker, "a") as output:
            output.write("write\n")
        return RESULT

    start.wait(10)
    queue.put(CallLedger(path).run("s", "c", PAYLOAD, operation))


if __name__ == "__main__":
    unittest.main()
