"""Durable at-most-once dispatch; pending reservations are never retried.

Use a persistent local filesystem path shared by all dispatchers. Deleting the
ledger discards its deduplication guarantees. IDs are bounded to 256 characters.
"""

import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing


def _error(code: str, message: str, *, uncertain: bool = False) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "uncertain": uncertain},
    }


def _encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class CallLedger:
    """Reserve before calling an operation, then persist its JSON envelope.

    Each invocation owns a connection. BEGIN IMMEDIATE serializes reservations
    across threads and processes; no transaction spans the external operation.
    Storage failures return errors without exposing paths or exception details.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = os.fspath(path)

    def _connect(self) -> sqlite3.Connection:
        if not self.path or self.path == ":memory:":
            raise sqlite3.OperationalError("A durable path is required")
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS github_calls (session_id TEXT NOT NULL, call_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, PRIMARY KEY (session_id, call_id))"
            )
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def _reserve(self, session_id: str, call_id: str, payload: str) -> dict | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, result FROM github_calls WHERE session_id = ? AND call_id = ?",
                (session_id, call_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO github_calls VALUES (?, ?, ?, NULL)",
                    (session_id, call_id, payload),
                )
                connection.commit()
                return None
            connection.commit()
            if row[0] != payload:
                return _error(
                    "call_conflict",
                    "This call ID was already used with different arguments.",
                )
            if row[1] is None:
                return _error(
                    "call_pending",
                    "This call is pending or its outcome is unknown. Do not retry the write.",
                    uncertain=True,
                )
            result = json.loads(row[1])
            if type(result) is not dict:
                raise ValueError("Invalid stored result")
            return result

    def run(
        self,
        session_id: str,
        call_id: str,
        payload: dict,
        operation: Callable[[], dict],
    ) -> dict:
        """Return cached envelope or execute once; never recover pending writes."""
        if any(
            type(value) is not str or not value.strip() or len(value) > 256
            for value in (session_id, call_id)
        ):
            return _error(
                "invalid_arguments",
                "Session and call IDs must be nonempty strings of at most 256 characters.",
            )
        try:
            if type(payload) is not dict:
                raise ValueError("Invalid payload")
            encoded = _encode(payload)
        except (TypeError, ValueError, RecursionError):
            return _error(
                "invalid_arguments", "Call payload must be a JSON serializable object."
            )
        try:
            existing = self._reserve(session_id, call_id, encoded)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return _error(
                "ledger_storage_error",
                "Call storage is unavailable; prior execution cannot be determined. Do not retry with a new call ID.",
                uncertain=True,
            )
        if existing is not None:
            return existing
        try:
            result = operation()
            if type(result) is not dict:
                raise ValueError("Invalid result")
            serialized = _encode(result)
        except Exception:
            result = _error(
                "operation_uncertain",
                "The operation outcome could not be confirmed. Do not retry the write.",
                uncertain=True,
            )
            serialized = _encode(result)
        return self._save(session_id, call_id, encoded, serialized)

    def _save(
        self, session_id: str, call_id: str, encoded: str, serialized: str
    ) -> dict:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE github_calls SET result = ? WHERE session_id = ? AND call_id = ? AND payload = ? AND result IS NULL",
                    (serialized, session_id, call_id, encoded),
                )
                if cursor.rowcount != 1:
                    raise sqlite3.OperationalError("Reservation missing")
                connection.commit()
        except (sqlite3.Error, OSError, ValueError):
            return _error(
                "ledger_storage_error",
                "The operation may have completed, but its result could not be saved. Do not retry the write.",
                uncertain=True,
            )
        return json.loads(serialized)
