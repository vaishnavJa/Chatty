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
    tools = ToolRegistry(
        schemas, lambda *args, calls=calls: calls.append(args) or {"ok": True}
    )
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


def test_registry_uses_all_declared_tools_and_separate_public_capabilities():
    from chatty.agents.tools import (
        READ_TOOL_NAMES,
        TOOL_CAPABILITIES,
        TOOLS,
        WRITE_TOOL_NAMES,
    )

    registry = ToolRegistry.from_module()
    assert executor_module.ALLOWED_TOOLS == frozenset(TOOLS)
    assert set(registry.validators) == set(TOOLS)
    assert READ_TOOL_NAMES | WRITE_TOOL_NAMES == set(TOOLS)
    assert not READ_TOOL_NAMES & WRITE_TOOL_NAMES
    assert len(registry.validators) > 4
    for schema in registry.schemas:
        assert not {"label", "requires_approval", "destructive"} & schema.keys()
        name = schema["name"]
        assert registry.capabilities[name] == {
            key: TOOL_CAPABILITIES[name][key]
            for key in ("label", "requires_approval", "destructive")
        }
        assert registry.capabilities[name]["requires_approval"] == (
            name in WRITE_TOOL_NAMES
        )


def test_every_declared_mutation_binds_review_and_deduplicates(settings, schemas):
    from chatty.agents.tools import WRITE_TOOL_NAMES

    for name in WRITE_TOOL_NAMES:
        calls = []
        schema = {**schemas[0], "name": name}
        executor = ToolExecutor(settings)
        executor.register(
            "s",
            ToolRegistry(
                [schema], lambda *args, calls=calls: calls.append(args) or {"ok": True}
            ),
        )
        proposal = {"title": "Exact reviewed proposal"}
        pending = executor.execute("s", "c", name, proposal)
        assert (
            json.loads(pending["output"])["error"]["code"] == "authorization_required"
        )
        assert not calls
        with pytest.raises(ExecutorError) as caught:
            executor.execute(
                "s", "c", name, {"title": "Changed after review"}, approved=True
            )
        assert caught.value.code == "call_conflict"
        for invalid in (1, "true", None):
            with pytest.raises(ExecutorError) as caught:
                executor.execute("s", "c", name, proposal, approved=invalid)
            assert caught.value.code == "invalid_approval"
        result = executor.execute("s", "c", name, proposal, approved=True)
        assert json.loads(result["output"])["ok"] is True
        assert executor.execute("s", "c", name, proposal, approved=True) == result
        assert calls == [(name, proposal)]


def test_every_declared_mutation_exception_is_uncertain_and_never_retried(
    settings, schemas
):
    from chatty.agents.tools import WRITE_TOOL_NAMES

    for name in WRITE_TOOL_NAMES:
        calls = []

        def failed(*args, calls=calls):
            calls.append(args)
            raise RuntimeError("private detail")

        executor = ToolExecutor(settings)
        executor.register("s", ToolRegistry([{**schemas[0], "name": name}], failed))
        first = executor.execute("s", "c", name, {"title": "Bound"}, approved=True)
        error = json.loads(first["output"])["error"]
        assert error["uncertain"] is True
        assert error["retryable"] is False
        assert "private detail" not in first["output"]
        assert (
            executor.execute("s", "c", name, {"title": "Bound"}, approved=True) == first
        )
        assert len(calls) == 1


def test_unknown_tool_schema_cannot_enable_an_unregistered_operation(schemas):
    with pytest.raises(ValueError, match="schema"):
        ToolRegistry(
            [{**schemas[0], "name": "arbitrary_github_request"}], lambda *_: {}
        )


def test_capability_metadata_mismatch_fails_closed(monkeypatch, schemas):
    monkeypatch.setitem(
        executor_module.TOOL_CAPABILITIES,
        "create_issue",
        {"label": "Create issue", "requires_approval": False, "destructive": False},
    )
    with pytest.raises(ValueError, match="capability"):
        ToolRegistry(schemas, lambda *_: {})
