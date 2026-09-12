import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

import chatty.integrations.gpt_live.executor as executor_module
from chatty.integrations.gpt_live.executor import (
    ExecutorError,
    ToolExecutor,
    ToolRegistry,
)


def test_concurrent_delivery_runs_once_and_returns_same_receipt(settings, schemas):
    started, release = threading.Event(), threading.Event()
    calls = []

    def runner(name, arguments):
        calls.append((name, arguments))
        started.set()
        assert release.wait(3)
        return {"number": 123}

    executor = ToolExecutor(settings)
    executor.register("s", ToolRegistry(schemas, runner))
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(
            executor.execute, "s", "c", "create_issue", {"title": "bug"}, approved=True
        )
        assert started.wait(1)
        duplicates = [
            pool.submit(
                executor.execute,
                "s",
                "c",
                "create_issue",
                {"title": "bug"},
                approved=True,
            )
            for _ in range(3)
        ]
        release.set()
        expected = first.result()
        assert all(future.result() == expected for future in duplicates)
    assert len(calls) == 1
    assert json.loads(expected["output"]) == {"number": 123}


def test_uncertain_write_is_cached_and_changed_payload_is_rejected(settings, schemas):
    calls = []

    def runner(*args):
        calls.append(args)
        raise TimeoutError("Remote side effect may have succeeded")

    executor = ToolExecutor(settings)
    executor.register("s", ToolRegistry(schemas, runner))
    original = executor.execute(
        "s", "c", "create_issue", {"title": "bug"}, approved=True
    )
    assert (
        executor.execute("s", "c", "create_issue", {"title": "bug"}, approved=True)
        == original
    )
    assert len(calls) == 1
    assert json.loads(original["output"])["error"]["retryable"] is False
    with pytest.raises(ExecutorError) as caught:
        executor.execute(
            "s", "c", "create_issue", {"title": "different"}, approved=True
        )
    assert caught.value.status == 409


def test_pending_retry_timeout_does_not_repeat_write(settings, schemas):
    started, release = threading.Event(), threading.Event()
    calls = []

    def runner(*args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    executor = ToolExecutor(replace(settings, duplicate_wait_seconds=0.01))
    executor.register("s", ToolRegistry(schemas, runner))
    with ThreadPoolExecutor() as pool:
        original = pool.submit(
            executor.execute, "s", "c", "create_issue", {"title": "bug"}, approved=True
        )
        assert started.wait(1)
        try:
            with pytest.raises(ExecutorError) as caught:
                executor.execute(
                    "s", "c", "create_issue", {"title": "bug"}, approved=True
                )
            assert caught.value.code == "tool_still_running"
        finally:
            release.set()
        result = original.result()
    assert (
        executor.execute("s", "c", "create_issue", {"title": "bug"}, approved=True)
        == result
    )
    assert len(calls) == 1


def test_async_tool_and_json_string_return(settings, schemas):
    async def runner(*_):
        return '{"ok":true,"number":45}'

    executor = ToolExecutor(settings)
    executor.register("s", ToolRegistry(schemas, runner))
    assert json.loads(
        executor.execute("s", "c", "create_issue", {"title": "bug"}, approved=True)[
            "output"
        ]
    ) == {"ok": True, "number": 45}


def test_limits_expiry_and_session_scoping(settings, schemas):
    now = [0]
    calls = []
    executor = ToolExecutor(
        replace(
            settings, max_sessions=2, max_calls_per_session=1, session_ttl_seconds=10
        ),
        clock=lambda: now[0],
    )
    tools = ToolRegistry(schemas, lambda *args: calls.append(args) or {"ok": True})
    executor.register("s1", tools)
    executor.register("s2", tools)
    with pytest.raises(ExecutorError, match="session limit"):
        executor.ensure_capacity()
    for session in ("s1", "s2"):
        executor.execute(
            session, "same-call-id", "create_issue", {"title": "bug"}, approved=True
        )
    assert len(calls) == 2
    with pytest.raises(ExecutorError, match="tool-call limit"):
        executor.execute("s1", "new", "create_issue", {"title": "bug"}, approved=True)
    now[0] = 11
    with pytest.raises(ExecutorError, match="expired"):
        executor.execute(
            "s1", "same-call-id", "create_issue", {"title": "bug"}, approved=True
        )
    executor.ensure_capacity()


def test_missing_module_and_broken_import_are_distinct(monkeypatch):
    def missing(_):
        raise ModuleNotFoundError(name="chatty.agents.tools")

    monkeypatch.setattr(executor_module.importlib, "import_module", missing)
    assert ToolRegistry.from_module().available is False

    def broken(_):
        raise ModuleNotFoundError(name="missing_dependency")

    monkeypatch.setattr(executor_module.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        ToolRegistry.from_module()
