"""The async Mongo client belongs to the event loop it is created on, so it must be created inside
the running loop (the app lifespan), never at import time, and closed - awaited - on shutdown.
PyMongo Async's client.close() is a coroutine (Motor's was not): forgetting the await would leak the
connection pool without any error. Runs on the fake and, with TEST_MONGO_URI, on a real *_test db.
"""

import importlib
from typing import Any

import pytest

from app.core import database
from app.main import app


def test_import_creates_no_client() -> None:
    """A client made at import time would be bound to whatever loop (or none) exists then."""
    fresh = importlib.reload(database)
    try:
        assert fresh._client is None and fresh._db is None
        assert fresh._gridfs is None and fresh._chat_gridfs is None
        with pytest.raises(RuntimeError, match="not initialized"):
            fresh.get_database()
    finally:
        importlib.reload(database)


async def test_clean_start_and_clean_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    awaited: list[Any] = []
    await database.connect_to_mongo()
    client = database._client
    assert client is not None
    cls = type(client)
    real_close = cls.close

    async def spy(self: Any) -> None:
        awaited.append(self)
        await real_close(self)

    monkeypatch.setattr(cls, "close", spy)
    assert (await database.get_database().command("ping"))["ok"] == 1.0
    await database.close_mongo_connection()
    assert awaited == [client]  # closed exactly once, and awaited


async def test_app_lifespan_connects_inside_the_loop_and_closes_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Any] = []
    closed: list[Any] = []
    real_connect = database.connect_to_mongo

    async def connect() -> None:
        await real_connect()
        client: Any = database._client
        created.append(client)
        cls = type(client)
        real_close = cls.close

        async def spy(self: Any) -> None:
            closed.append(self)
            await real_close(self)

        monkeypatch.setattr(cls, "close", spy)

    monkeypatch.setattr("app.main.connect_to_mongo", connect)
    async with app.router.lifespan_context(app):
        assert len(created) == 1 and closed == []
        assert (await database.get_database().command("ping"))["ok"] == 1.0
        assert await database.get_database().list_collection_names() is not None
    assert closed == created
