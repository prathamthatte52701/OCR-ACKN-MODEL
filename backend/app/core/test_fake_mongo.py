"""Tests of the fake Mongo itself (backend/fake_mongo.py).

Two groups:
- plain tests of the fake: unsupported operators raise NotImplementedError, unique-index errors use
  the real error type, ObjectId and date handling, copies instead of references, GridFS behaviour.
- a DIFFERENTIAL test: the same operations run against the fake AND a real MongoDB (TEST_MONGO_URI,
  a *_test database) and must give the same results. Skipped when TEST_MONGO_URI is not set.
"""

import asyncio
import datetime as dt
import os
import re
import uuid
from typing import Any

import pytest
from bson import ObjectId
from gridfs.errors import NoFile
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import fake_mongo

REAL_URI = os.environ.get("TEST_MONGO_URI", "").strip()


@pytest.fixture
def fdb() -> Any:
    """A fresh fake database (always the fake, whatever the suite is running on)."""
    fake_mongo.reset_store()
    client = fake_mongo.FakeAsyncClient(tz_aware=True)
    yield client["ackn_fake_unit_test"]
    fake_mongo.reset_store()


# ------------------------------------------------------------------ plain tests of the fake
async def test_unsupported_query_operator_raises(fdb: Any) -> None:
    await fdb.c.insert_one({"a": 1})
    with pytest.raises(NotImplementedError, match=r"\$elemMatch"):
        await fdb.c.find_one({"a": {"$elemMatch": {"x": 1}}})
    with pytest.raises(NotImplementedError, match=r"\$where"):
        await fdb.c.count_documents({"$where": "1"})


async def test_unsupported_update_operator_raises(fdb: Any) -> None:
    await fdb.c.insert_one({"a": [1]})
    with pytest.raises(NotImplementedError, match=r"\$push"):
        await fdb.c.update_one({}, {"$push": {"a": 2}})
    with pytest.raises(NotImplementedError):
        await fdb.c.update_one({}, {"a": 5})  # replacement-style update


async def test_unsupported_stage_expression_and_method_raise(fdb: Any) -> None:
    await fdb.c.insert_one({"a": 1})
    with pytest.raises(NotImplementedError, match=r"\$lookup"):
        await (await fdb.c.aggregate([{"$lookup": {}}])).to_list(None)
    with pytest.raises(NotImplementedError, match=r"\$toUpper"):
        await (await fdb.c.aggregate([{"$addFields": {"x": {"$toUpper": "$a"}}}])).to_list(None)
    with pytest.raises(NotImplementedError, match="bulk_write"):
        await fdb.c.bulk_write([])
    with pytest.raises(NotImplementedError, match="options"):
        await fdb.c.find_one({}, no_such_option=1)


async def test_unique_index_raises_the_real_error_type(fdb: Any) -> None:
    await fdb.c.create_index("email", unique=True)
    await fdb.c.insert_one({"email": "a@x"})
    with pytest.raises(DuplicateKeyError):
        await fdb.c.insert_one({"email": "a@x"})
    await fdb.c.insert_one({"email": "b@x"})
    with pytest.raises(DuplicateKeyError):
        await fdb.c.update_one({"email": "b@x"}, {"$set": {"email": "a@x"}})
    with pytest.raises(DuplicateKeyError):  # an upsert that would insert a duplicate
        await fdb.c.update_one({"email": "a@x", "n": 1}, {"$set": {"z": 1}}, upsert=True)


async def test_partial_unique_index_only_counts_matching_documents(fdb: Any) -> None:
    await fdb.c.create_index(
        [("userId", 1), ("name", 1)], unique=True, partialFilterExpression={"active": True}
    )
    await fdb.c.insert_one({"userId": 1, "name": "n", "active": False})
    await fdb.c.insert_one({"userId": 1, "name": "n", "active": False})  # not covered: fine
    await fdb.c.insert_one({"userId": 1, "name": "n", "active": True})
    with pytest.raises(DuplicateKeyError):
        await fdb.c.insert_one({"userId": 1, "name": "n", "active": True})


async def test_duplicate_id_and_object_id_handling(fdb: Any) -> None:
    oid = ObjectId()
    res = await fdb.c.insert_one({"_id": oid, "v": 1})
    assert res.inserted_id == oid
    with pytest.raises(DuplicateKeyError):
        await fdb.c.insert_one({"_id": oid})
    doc: dict = {"v": 2}
    res2 = await fdb.c.insert_one(doc)
    assert isinstance(res2.inserted_id, ObjectId) and doc["_id"] == res2.inserted_id
    assert (await fdb.c.find_one({"_id": oid}))["v"] == 1
    assert await fdb.c.find_one({"_id": str(oid)}) is None  # a string is not an ObjectId


async def test_dates_are_utc_milliseconds_and_tz_aware(fdb: Any) -> None:
    naive = dt.datetime(2026, 1, 2, 3, 4, 5, 123456)
    aware_ist = dt.datetime(
        2026, 1, 2, 8, 34, 5, 123456, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))
    )
    await fdb.c.insert_many([{"k": "naive", "d": naive}, {"k": "ist", "d": aware_ist}])
    a = await fdb.c.find_one({"k": "naive"})
    b = await fdb.c.find_one({"k": "ist"})
    assert a["d"].tzinfo is not None and a["d"].microsecond == 123000
    assert a["d"] == b["d"] == dt.datetime(2026, 1, 2, 3, 4, 5, 123000, tzinfo=dt.UTC)
    assert await fdb.c.count_documents({"d": {"$gte": a["d"]}}) == 2
    plain = fake_mongo.FakeAsyncClient(tz_aware=False)[
        "ackn_fake_unit_test"
    ]  # a non tz_aware client
    assert (await plain.c.find_one({"k": "ist"}))["d"].tzinfo is None


async def test_documents_are_copies_not_references(fdb: Any) -> None:
    source = {"a": {"b": [1, 2]}}
    await fdb.c.insert_one(source)
    source["a"]["b"].append(99)  # mutating the caller's dict after insert changes nothing stored
    got = await fdb.c.find_one({})
    assert got["a"]["b"] == [1, 2]
    got["a"]["b"].append(7)  # mutating what find returned changes nothing stored
    assert (await fdb.c.find_one({}))["a"]["b"] == [1, 2]
    listed = await fdb.c.find({}).to_list(None)
    listed[0]["a"] = "x"
    assert (await fdb.c.find_one({}))["a"] == {"b": [1, 2]}


async def test_bool_is_not_an_int_and_null_matches_missing(fdb: Any) -> None:
    await fdb.c.insert_many([{"n": 1}, {"n": True}, {"n": None}, {"other": 1}])
    assert await fdb.c.count_documents({"n": 1}) == 1
    assert await fdb.c.count_documents({"n": True}) == 1
    assert await fdb.c.count_documents({"n": None}) == 2  # null and missing both match
    assert await fdb.c.count_documents({"n": {"$exists": False}}) == 1
    assert await fdb.c.count_documents({"n": {"$ne": 1}}) == 3


async def test_sort_order_across_types_and_stable_multi_key(fdb: Any) -> None:
    await fdb.c.insert_many(
        [{"v": "b", "i": 1}, {"v": 5, "i": 2}, {"i": 3}, {"v": "a", "i": 4}, {"v": "a", "i": 0}]
    )
    asc = [d["i"] for d in await fdb.c.find({}).sort([("v", 1), ("i", 1)]).to_list(None)]
    assert asc == [3, 2, 0, 4, 1]  # missing < number < "a"s (by i) < "b"
    desc = [d["i"] for d in await fdb.c.find({}).sort([("v", -1), ("i", -1)]).to_list(None)]
    assert desc == [1, 4, 0, 2, 3]


async def test_find_one_and_update_claims_exactly_once(fdb: Any) -> None:
    await fdb.c.insert_one({"_id": 1, "used": False})
    first = await fdb.c.find_one_and_update({"_id": 1, "used": False}, {"$set": {"used": True}})
    second = await fdb.c.find_one_and_update({"_id": 1, "used": False}, {"$set": {"used": True}})
    assert first is not None and first["used"] is False  # the document BEFORE the update
    assert second is None
    after = await fdb.c.find_one_and_update(
        {"_id": 1}, {"$inc": {"n": 1}}, return_document=ReturnDocument.AFTER
    )
    assert after["n"] == 1


async def test_upsert_sets_equality_fields_and_set_on_insert(fdb: Any) -> None:
    res = await fdb.c.update_one(
        {"k": "x", "n": {"$gt": 0}}, {"$set": {"a": 1}, "$setOnInsert": {"s": 2}}, upsert=True
    )
    assert res.upserted_id is not None and res.matched_count == 0
    doc = await fdb.c.find_one({"k": "x"})
    assert doc["a"] == 1 and doc["s"] == 2 and "n" not in doc
    await fdb.c.update_one({"k": "x"}, {"$set": {"a": 5}, "$setOnInsert": {"s": 99}}, upsert=True)
    again = await fdb.c.find_one({"k": "x"})
    assert again["a"] == 5 and again["s"] == 2
    assert await fdb.c.count_documents({}) == 1


async def test_regex_in_nin_and_size_operators(fdb: Any) -> None:
    await fdb.c.insert_many([{"s": "Abc"}, {"s": "xBc"}, {"s": "zzz"}, {"t": [1, 2]}])
    assert await fdb.c.count_documents({"s": {"$regex": "bc", "$options": "i"}}) == 2
    assert await fdb.c.count_documents({"s": {"$regex": "^a"}}) == 0
    assert await fdb.c.count_documents({"s": {"$not": re.compile(r"^\d")}}) == 4
    assert await fdb.c.count_documents({"s": {"$in": ["zzz", "nope"]}}) == 1
    assert await fdb.c.count_documents({"s": {"$nin": ["zzz"]}}) == 3
    assert await fdb.c.count_documents({"t": {"$size": 2}}) == 1


async def test_gridfs_upload_download_delete_and_missing(fdb: Any) -> None:
    bucket = fake_mongo.FakeGridFSBucket(fdb)
    grid_in = bucket.open_upload_stream("f.bin", metadata={"contentType": "x/y"})
    await grid_in.write(b"hello " * 100_000)  # more than one chunk
    await grid_in.close()
    stream = await bucket.open_download_stream(grid_in._id)
    assert await stream.read() == b"hello " * 100_000
    meta = await fdb["fs.files"].find_one({"_id": grid_in._id})
    assert meta["length"] == 600_000 and meta["metadata"] == {"contentType": "x/y"}
    assert await fdb["fs.chunks"].count_documents({"files_id": grid_in._id}) == 3
    await bucket.delete(grid_in._id)
    assert (
        await fdb["fs.files"].count_documents({}) == 0
        and await fdb["fs.chunks"].count_documents({}) == 0
    )
    with pytest.raises(NoFile):
        await bucket.delete(grid_in._id)
    with pytest.raises(NoFile):
        await bucket.open_download_stream(ObjectId())
    chat = fake_mongo.FakeGridFSBucket(fdb, bucket_name="chatfs")
    gi = chat.open_upload_stream("c.bin")
    await gi.write(b"z")
    await gi.close()
    assert await fdb["chatfs.files"].count_documents({}) == 1
    assert await fdb["fs.files"].count_documents({}) == 0


async def test_aggregate_group_facet_and_expr(fdb: Any) -> None:
    await fdb.c.insert_many(
        [
            {
                "u": 1,
                "s": "processed",
                "n": 5,
                "d": dt.datetime(2026, 1, 1, 20, 0, tzinfo=dt.UTC),
            },
            {
                "u": 1,
                "s": "failed",
                "n": 7,
                "d": dt.datetime(2026, 1, 1, 10, 0, tzinfo=dt.UTC),
            },
            {
                "u": 2,
                "s": "processed",
                "n": 1,
                "d": dt.datetime(2026, 1, 2, 1, 0, tzinfo=dt.UTC),
            },
        ]
    )
    grouped = await (
        await fdb.c.aggregate(
            [
                {
                    "$group": {
                        "_id": "$u",
                        "n": {"$sum": 1},
                        "t": {"$max": "$d"},
                        "tot": {"$sum": "$n"},
                    }
                }
            ]
        )
    ).to_list(None)
    by = {g["_id"]: g for g in grouped}
    assert by[1]["n"] == 2 and by[1]["tot"] == 12 and by[2]["n"] == 1
    days = await (
        await fdb.c.aggregate(
            [
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$d",
                                "timezone": "+05:30",
                            }
                        },
                        "n": {"$sum": 1},
                    }
                }
            ]
        )
    ).to_list(None)
    assert {g["_id"]: g["n"] for g in days} == {"2026-01-01": 1, "2026-01-02": 2}
    facet = await (
        await fdb.c.aggregate(
            [
                {"$match": {"u": 1}},
                {
                    "$facet": {
                        "all": [{"$count": "n"}],
                        "proc": [
                            {"$match": {"$expr": {"$eq": ["$s", "processed"]}}},
                            {"$count": "n"},
                        ],
                        "none": [{"$match": {"u": 9}}, {"$count": "n"}],
                    }
                },
            ]
        )
    ).to_list(1)
    assert (
        facet[0]["all"] == [{"n": 2}] and facet[0]["proc"] == [{"n": 1}] and facet[0]["none"] == []
    )


async def test_sync_client_shares_the_same_store(fdb: Any) -> None:
    await fdb.c.insert_one({"_id": 1, "v": 1})
    sync = fake_mongo.FakeSyncClient()
    sync["ackn_fake_unit_test"].c.update_one({"_id": 1}, {"$set": {"v": 2}})
    assert (await fdb.c.find_one({"_id": 1}))["v"] == 2


async def test_concurrent_tasks_interleave_between_awaited_operations(fdb: Any) -> None:
    """Like a real server, an awaited database call is a point where other tasks get to run (each
    call itself stays atomic). Without that, asyncio.gather() of two requests ran one after the
    other and a "race" test could never see a race."""
    order: list[str] = []

    async def worker(name: str) -> None:
        for i in range(3):
            await fdb.c.insert_one({"w": name, "i": i})
            order.append(name)

    await asyncio.gather(worker("a"), worker("b"))
    assert order == ["a", "b", "a", "b", "a", "b"]
    assert await fdb.c.count_documents({}) == 6


async def test_interleaving_keeps_every_single_operation_atomic(fdb: Any) -> None:
    await fdb.c.insert_one({"_id": 1, "used": False, "n": 0})

    async def claim() -> Any:
        return await fdb.c.find_one_and_update({"_id": 1, "used": False}, {"$set": {"used": True}})

    results = await asyncio.gather(*[claim() for _ in range(8)])
    assert sum(r is not None for r in results) == 1  # exactly one task wins the claim

    async def bump() -> None:
        for _ in range(10):
            await fdb.c.update_one({"_id": 1}, {"$inc": {"n": 1}})

    await asyncio.gather(*[bump() for _ in range(5)])
    assert (await fdb.c.find_one({"_id": 1}))["n"] == 50  # no lost update between interleaved tasks


async def test_cursors_gridfs_and_database_calls_also_yield(fdb: Any) -> None:
    await fdb.c.insert_many([{"i": i} for i in range(3)])
    bucket = fake_mongo.FakeGridFSBucket(fdb)
    order: list[str] = []

    async def cursor_user() -> None:
        order.append("c0")
        await fdb.c.find({}).to_list(None)
        order.append("c1")
        async for _ in await fdb.c.aggregate([{"$match": {}}]):
            pass
        order.append("c2")

    async def gridfs_user() -> None:
        order.append("g0")
        await bucket.upload_from_stream("f", b"x")
        order.append("g1")
        await fdb.list_collection_names()
        order.append("g2")

    await asyncio.gather(cursor_user(), gridfs_user())
    assert order == ["c0", "g0", "c1", "g1", "c2", "g2"]


# ---------------------------------------------------- differential: fake vs a real MongoDB
@pytest.mark.skipif(
    not REAL_URI, reason="differential test: set TEST_MONGO_URI to a real *_test database"
)
async def test_differential_fake_vs_real() -> None:
    RealClient = (
        fake_mongo.REAL_ASYNC_CLIENT
    )  # noqa: N806 (saved by conftest before the fake was patched in)
    name = os.environ.get("ACKN_TEST_DB", "ackn_AI_model_test")
    assert name.endswith("_test")
    real_db = RealClient(REAL_URI, tz_aware=True, serverSelectionTimeoutMS=10000)[name]
    fake_mongo.reset_store()
    fake_db = fake_mongo.FakeAsyncClient(tz_aware=True)[name]
    coll = "diff_" + uuid.uuid4().hex[:8]
    try:
        for db in (real_db, fake_db):
            c = db[coll]
            await c.create_index("email", unique=True, partialFilterExpression={"active": True})
            await c.insert_many(
                [
                    {
                        "_id": i,
                        "email": f"u{i}@x",
                        "n": i % 7,
                        "s": ["b", "A", "c", None][i % 4],
                        "active": i % 2 == 0,
                        "d": dt.datetime(2026, 1, 1 + i % 28, 12, i % 60, tzinfo=dt.UTC),
                        "tags": ["x", "y"][: i % 3],
                    }
                    for i in range(60)
                ]
            )
        queries: list[tuple[dict, Any, int, int]] = [
            ({}, [("_id", 1)], 0, 0),
            ({"n": {"$gte": 2, "$lt": 5}}, [("n", -1), ("_id", 1)], 3, 7),
            ({"s": None}, [("_id", 1)], 0, 0),
            ({"s": {"$ne": "b"}}, [("_id", 1)], 5, 5),
            ({"$or": [{"n": 1}, {"s": "c"}]}, [("s", 1), ("_id", -1)], 0, 12),
            ({"$and": [{"active": True}, {"n": {"$in": [1, 2, 3]}}]}, [("_id", 1)], 0, 0),
            ({"s": {"$regex": "^a", "$options": "i"}}, [("_id", 1)], 0, 0),
            ({"tags": "x"}, [("_id", 1)], 0, 0),
            ({"tags": {"$size": 2}}, [("_id", 1)], 0, 0),
            ({"s": {"$exists": True, "$nin": ["b"]}}, [("d", -1), ("_id", 1)], 2, 9),
        ]
        for flt, sort, skip, limit in queries:
            outs = []
            for db in (real_db, fake_db):
                cur = db[coll].find(flt).sort(sort)
                if skip:
                    cur = cur.skip(skip)
                if limit:
                    cur = cur.limit(limit)
                outs.append(await cur.to_list(None))
            assert outs[0] == outs[1], f"find differs for {flt}"
            counts = [await db[coll].count_documents(flt) for db in (real_db, fake_db)]
            assert counts[0] == counts[1]
        # updates: results and the stored data must match
        upd = [
            ({"n": 3}, {"$set": {"flag": 1}, "$inc": {"n": 10}}),
            ({"_id": 5}, {"$unset": {"s": ""}}),
            ({"_id": 999}, {"$set": {"x": 1}}),
        ]
        for flt, u in upd:
            rs = [await db[coll].update_many(flt, u) for db in (real_db, fake_db)]
            assert (rs[0].matched_count, rs[0].modified_count) == (
                rs[1].matched_count,
                rs[1].modified_count,
            )
        ups = [
            await db[coll].update_one(
                {"email": "new@x"}, {"$set": {"a": 1}, "$setOnInsert": {"_id": 1000}}, upsert=True
            )
            for db in (real_db, fake_db)
        ]
        assert ups[0].upserted_id == ups[1].upserted_id == 1000
        dumps = [await db[coll].find({}).sort("_id", 1).to_list(None) for db in (real_db, fake_db)]
        assert dumps[0] == dumps[1]
        # unique index (partial): same error type on both
        for db in (real_db, fake_db):
            with pytest.raises(DuplicateKeyError):
                await db[coll].insert_one({"_id": 2000, "email": "u2@x", "active": True})
            await db[coll].insert_one(
                {"_id": 2001, "email": "u2@x", "active": False}
            )  # outside the partial filter
        # atomic claim
        claims = []
        for db in (real_db, fake_db):
            a = await db[coll].find_one_and_update(
                {"_id": 3, "claimed": {"$ne": True}}, {"$set": {"claimed": True}}
            )
            b = await db[coll].find_one_and_update(
                {"_id": 3, "claimed": {"$ne": True}}, {"$set": {"claimed": True}}
            )
            claims.append((a is not None and a.get("claimed"), b))
        assert claims[0] == claims[1] == (None, None)
        # aggregation: group + sort
        pipe: list[dict[str, Any]] = [
            {"$match": {"active": True}},
            {"$group": {"_id": "$n", "c": {"$sum": 1}, "m": {"$max": "$d"}}},
            {"$sort": {"_id": 1}},
        ]
        aggs = [await (await db[coll].aggregate(pipe)).to_list(None) for db in (real_db, fake_db)]
        assert aggs[0] == aggs[1]
        # GridFS: upload / download / delete
        real_bucket = fake_mongo.REAL_GRIDFS_BUCKET(real_db, bucket_name="difftest")
        fake_bucket = fake_mongo.FakeGridFSBucket(fake_db, bucket_name="difftest")
        payload = os.urandom(300_000)
        for bucket in (real_bucket, fake_bucket):
            gi = bucket.open_upload_stream("p.bin", metadata={"contentType": "a/b"})
            await gi.write(payload)
            await gi.close()
            out = await (await bucket.open_download_stream(gi._id)).read()
            assert out == payload
            await bucket.delete(gi._id)
            with pytest.raises(NoFile):
                await bucket.delete(gi._id)
        for db in (real_db, fake_db):
            assert await db["difftest.files"].count_documents({}) == 0
            assert await db["difftest.chunks"].count_documents({}) == 0
    finally:
        await real_db.drop_collection(coll)
        for extra in ("difftest.files", "difftest.chunks"):
            await real_db.drop_collection(extra)
        fake_mongo.reset_store()
