"""Shutdown order of the real app lifespan: the startup background tasks (upload recovery,
chat-file expiry sweep) must be cancelled AND awaited before the Mongo client is closed. PyMongo
Async's close() is a coroutine and stricter than Motor's, so closing while a task is inside a
database call is a race.

The tasks are made provably "inside an awaited database call" by holding the cursor's to_list (the
call both tasks make first); the hold is never released, like a slow server. Works on the fake and,
with TEST_MONGO_URI, on a real *_test database."""

import asyncio
import gc
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from loguru import logger

import app.main as main_mod
import fake_mongo
from app.core import database
from app.main import app

USE_REAL = bool(os.environ.get("TEST_MONGO_URI", "").strip())


def _cursor_class() -> Any:
    if USE_REAL:
        from pymongo.asynchronous.cursor import AsyncCursor

        return AsyncCursor
    return fake_mongo._AsyncCursor


class Probe:
    """Records database calls in flight and the moment the client is closed."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.hold = True
        self.never = asyncio.Event()  # never set: the "call" stays in flight until cancelled

    def installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls = _cursor_class()
        orig = cls.to_list
        probe = self

        async def to_list(self_: Any, *a: Any, **k: Any) -> Any:
            probe.events.append("call-start")
            try:
                if probe.hold:
                    await probe.never.wait()
                return await orig(self_, *a, **k)
            finally:
                probe.events.append("call-end")

        monkeypatch.setattr(cls, "to_list", to_list)

    def spy_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if getattr(self, "_spied", False):
            return  # the client class is the same on every start; spy once
        self._spied = True
        client_cls: Any = type(database._client)
        orig = client_cls.close
        probe = self

        async def close(self_: Any) -> None:
            probe.events.append("close")
            await orig(self_)

        monkeypatch.setattr(client_cls, "close", close)

    async def wait_calls(self, n: int) -> None:
        for _ in range(500):
            if self.events.count("call-start") >= n:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"only {self.events.count('call-start')} database calls started")

    def in_flight(self) -> int:
        return self.events.count("call-start") - self.events.count("call-end")


@pytest.fixture
async def env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    if not USE_REAL:
        fake_mongo.reset_store()
    problems: list[str] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _l, ctx: problems.append(str(ctx.get("message"))))
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="INFO")
    monkeypatch.setattr(main_mod, "configure_logging", lambda: None)  # it would remove my log sink
    probe = Probe()
    probe.installed(monkeypatch)
    yield {"probe": probe, "problems": problems, "logs": logs, "mp": monkeypatch}
    probe.never.set()
    for name in ("recovery_task", "chat_expiry_task"):  # never leave a task behind, whatever failed
        t = getattr(app.state, name, None)
        if t is not None and not t.done():
            t.cancel()
    await asyncio.sleep(0)
    for name in ("recovery_task", "chat_expiry_task"):
        if hasattr(app.state, name):
            delattr(app.state, name)
    gc.collect()
    await asyncio.sleep(0)
    logger.remove(sink)
    assert not [p for p in problems if "pending" in p or "never retrieved" in p], problems


async def _run_and_stop(env: dict[str, Any], *, hold: bool = True, wait: int = 2) -> dict[str, Any]:
    probe: Probe = env["probe"]
    probe.hold = hold
    tasks: dict[str, Any] = {}
    async with app.router.lifespan_context(app):
        tasks = {
            "recovery": app.state.recovery_task,
            "expiry": app.state.chat_expiry_task,
        }
        probe.spy_close(env["mp"])
        if wait:
            await probe.wait_calls(wait)
    return tasks


async def test_tasks_are_finished_before_mongo_is_closed(env: dict[str, Any]) -> None:
    probe: Probe = env["probe"]
    tasks = await _run_and_stop(env)  # both tasks are inside a held database call at shutdown
    assert "close" in probe.events
    close_at = probe.events.index("close")
    assert probe.events[:close_at].count("call-end") == 2, probe.events  # both calls ended first
    assert probe.in_flight() == 0
    assert all(t.done() for t in tasks.values())
    assert all(t.cancelled() for t in tasks.values())


async def test_shutdown_when_recovery_already_finished(env: dict[str, Any]) -> None:
    probe: Probe = env["probe"]
    probe.hold = True
    async with app.router.lifespan_context(app):
        recovery = app.state.recovery_task
        probe.spy_close(env["mp"])
        await probe.wait_calls(2)
        probe.never.set()  # let both calls through: recovery (empty db) ends, sweep sleeps
        probe.hold = False
        for _ in range(500):
            if recovery.done():
                break
            await asyncio.sleep(0.01)
        assert recovery.done() and not recovery.cancelled()
    close_at = probe.events.index("close")
    assert app.state.chat_expiry_task.done()
    assert probe.events[:close_at].count("call-start") == probe.events[:close_at].count("call-end")


async def test_shutdown_right_after_startup_before_tasks_ran(env: dict[str, Any]) -> None:
    probe: Probe = env["probe"]
    probe.hold = False
    tasks = await _run_and_stop(env, hold=False, wait=0)  # no await between start and stop
    assert all(t.done() for t in tasks.values())
    assert probe.events.count("close") == 1
    assert probe.in_flight() == 0


async def test_task_that_ignores_cancel_cannot_hang_shutdown(env: dict[str, Any]) -> None:
    release = asyncio.Event()
    running = asyncio.Event()

    async def stubborn(*_a: Any, **_k: Any) -> None:
        running.set()
        while not release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue  # swallows every cancel

    env["mp"].setattr(main_mod, "run_expiry_forever", stubborn)
    env["mp"].setattr(main_mod, "SHUTDOWN_TASK_TIMEOUT", 0.3, raising=False)
    probe: Probe = env["probe"]
    probe.hold = False
    cm = app.router.lifespan_context(app)
    await cm.__aenter__()  # startup (a real server needs a while to connect): not timed
    try:
        probe.spy_close(env["mp"])
        await running.wait()  # the task is really running, so cancel() is swallowed
        started = time.monotonic()
        await cm.__aexit__(None, None, None)  # a hang here is caught by pytest's --timeout
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 3, elapsed
    assert probe.events.count("close") == 1  # still closed, after the timeout
    assert any("did not stop" in m for m in env["logs"]), env["logs"]


async def test_task_that_failed_is_logged_by_class_only(env: dict[str, Any]) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("secret-detail-must-not-be-logged")

    env["mp"].setattr(main_mod, "run_expiry_forever", boom)
    probe: Probe = env["probe"]
    probe.hold = False
    async with app.router.lifespan_context(app):
        probe.spy_close(env["mp"])
        await asyncio.sleep(0.05)  # the task has already died with its error
    text = "\n".join(env["logs"])
    assert "RuntimeError" in text
    assert "secret-detail-must-not-be-logged" not in text
    assert probe.events.count("close") == 1


async def test_two_shutdowns_in_a_row(env: dict[str, Any]) -> None:
    probe: Probe = env["probe"]
    first = await _run_and_stop(env)
    second = await _run_and_stop(env)
    assert all(t.done() for t in (*first.values(), *second.values()))
    assert probe.events.count("close") == 2
    assert probe.in_flight() == 0
