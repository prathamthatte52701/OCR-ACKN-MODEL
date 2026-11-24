# ruff: noqa: E501, UP017
"""In-process fake MongoDB for the ACKN backend tests (PyMongo Async, PyMongo sync and GridFS look-alikes).

Written from what ACKN really uses (see the usage scan kept with the project notes), not as a general
Mongo clone. Anything outside that list raises NotImplementedError that names the operation, so a test
can never pass because an operator was silently ignored.

Supported
- Collection (async PyMongo style and sync PyMongo style, one shared in-memory store):
  insert_one, insert_many, find_one, find (cursor: sort, skip, limit, to_list, async for), count_documents,
  estimated_document_count, update_one, update_many, delete_one, delete_many, find_one_and_update,
  aggregate, create_index, drop_index, list_indexes, distinct, drop.
- Query: $eq $ne $gt $gte $lt $lte $in $nin $exists $regex(+$options) $not $size $or $and $nor $expr,
  dotted paths, array-contains matching, compiled regex values.
- Update: $set $unset $inc $setOnInsert (dotted paths), upsert, ReturnDocument.
- Aggregation: $match $group $sort $skip $limit $project(exclusion) $addFields $count $facet;
  accumulators $sum $max; expressions $cond $eq $ne $and $gte $lt $type $concat $substrCP $regexMatch
  $ifNull $dateToString and field paths; collation strength < 3 (case-insensitive string compare).
- Indexes: unique (also compound, sparse, partialFilterExpression) -> DuplicateKeyError like real Mongo;
  TTL (expireAfterSeconds) is recorded but NOT enforced (the real TTL monitor runs in the background).
- GridFS bucket: open_upload_stream, upload_from_stream, open_download_stream, delete (NoFile when missing), with the real
  fs.files / fs.chunks collections.
- Behaviours that matter: documents are deep-copied in and out, BSON ordering across types, bool != int,
  datetimes are stored as UTC with millisecond precision and read back tz-aware (tz_aware=True) or naive.
"""

from __future__ import annotations

import asyncio
import copy
import datetime as _dt
import re
import threading
from collections.abc import Callable
from typing import Any

from bson import ObjectId
from gridfs.errors import NoFile
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

_LOCK = threading.RLock()
_STORE: dict[str, dict[str, _CollData]] = {}
_MISSING = object()
REAL_ASYNC_CLIENT: Any = (
    None  # set by conftest: the real pymongo AsyncMongoClient (for the differential test)
)
REAL_GRIDFS_BUCKET: Any = None  # set by conftest: the real gridfs AsyncGridFSBucket class
_CHUNK = 255 * 1024
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def nope(what: str) -> NotImplementedError:
    return NotImplementedError(
        f"fake_mongo does not implement {what}; add it (from real usage) or use a real *_test database"
    )


async def _yield() -> None:
    """Every awaited database call is a point where other tasks may run, like a real server round
    trip (each call still runs atomically once it starts). No timed sleep, just one loop turn."""
    await asyncio.sleep(0)


def reset_store() -> None:
    """Drops every fake database (the test fixtures call this between tests)."""
    with _LOCK:
        _STORE.clear()


class _CollData:
    def __init__(self) -> None:
        self.docs: dict[Any, dict] = {}
        self.indexes: dict[str, dict] = {"_id_": {"key": [("_id", 1)], "name": "_id_"}}


# ---------------------------------------------------------------- value helpers
def _norm_dt(v: _dt.datetime) -> _dt.datetime:
    if v.tzinfo is None:
        v = v.replace(tzinfo=_dt.timezone.utc)
    v = v.astimezone(_dt.timezone.utc)
    return v.replace(microsecond=(v.microsecond // 1000) * 1000)


def _clean_in(v: Any) -> Any:
    """Deep copy for storing: dates become UTC/ms, tuples become lists."""
    if isinstance(v, _dt.datetime):
        return _norm_dt(v)
    if isinstance(v, dict):
        return {k: _clean_in(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean_in(x) for x in v]
    return copy.deepcopy(v)


def _clean_out(v: Any, tz_aware: bool) -> Any:
    if isinstance(v, _dt.datetime):
        return v if tz_aware else v.replace(tzinfo=None)
    if isinstance(v, dict):
        return {k: _clean_out(x, tz_aware) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean_out(x, tz_aware) for x in v]
    return copy.deepcopy(v)


def _type_rank(v: Any) -> int:
    if v is _MISSING or v is None:
        return 1
    if isinstance(v, bool):
        return 9
    if isinstance(v, (int, float)):
        return 2
    if isinstance(v, str):
        return 3
    if isinstance(v, dict):
        return 4
    if isinstance(v, list):
        return 5
    if isinstance(v, (bytes, bytearray)):
        return 6
    if isinstance(v, ObjectId):
        return 7
    if isinstance(v, _dt.datetime):
        return 10
    if isinstance(v, re.Pattern):
        return 11
    return 99


def _cmp(a: Any, b: Any, ci: bool = False) -> int:
    ra, rb = _type_rank(a), _type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 1:
        return 0
    if ra == 3 and ci:
        a, b = a.casefold(), b.casefold()
    if ra == 4:
        for (ka, va), (kb, vb) in zip(a.items(), b.items(), strict=False):
            if ka != kb:
                return -1 if ka < kb else 1
            c = _cmp(va, vb, ci)
            if c:
                return c
        return (len(a) > len(b)) - (len(a) < len(b))
    if ra == 5:
        for x, y in zip(a, b, strict=False):
            c = _cmp(x, y, ci)
            if c:
                return c
        return (len(a) > len(b)) - (len(a) < len(b))
    if ra == 7:
        a, b = a.binary, b.binary
    if ra == 6:
        a, b = bytes(a), bytes(b)
    if ra == 10:
        a, b = _norm_dt(a), _norm_dt(b)
    return (a > b) - (a < b)


def _eq(a: Any, b: Any) -> bool:
    if a is _MISSING:
        a = None
    if b is _MISSING:
        b = None
    return _type_rank(a) == _type_rank(b) and _cmp(a, b) == 0


# ---------------------------------------------------------------- paths
def _get(doc: Any, path: str) -> Any:
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return _MISSING
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            i = int(part)
            if i >= len(cur):
                return _MISSING
            cur = cur[i]
        else:
            return _MISSING
    return cur


def _candidates(doc: dict, path: str) -> list[Any]:
    """Values a query path can see: the value itself plus, for an array, each element."""
    v = _get(doc, path)
    if isinstance(v, list):
        return [v, *v]
    return [v]


def _set_path(doc: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _unset_path(doc: dict, path: str) -> None:
    parts = path.split(".")
    cur: Any = doc
    for p in parts[:-1]:
        cur = cur.get(p) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            return
    cur.pop(parts[-1], None)


# ---------------------------------------------------------------- query matching
def _regex_of(spec: Any, options: str = "") -> re.Pattern:
    if isinstance(spec, re.Pattern):
        return spec
    flags = 0
    if "i" in options:
        flags |= re.IGNORECASE
    if "m" in options:
        flags |= re.MULTILINE
    if "s" in options:
        flags |= re.DOTALL
    if "x" in options:
        flags |= re.VERBOSE
    return re.compile(spec, flags)


_TYPE_NAMES = {
    "string": str,
    "bool": bool,
    "date": _dt.datetime,
    "objectId": ObjectId,
    "array": list,
    "object": dict,
}


def _type_name(v: Any) -> str:
    if v is _MISSING:
        return "missing"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    for name, t in _TYPE_NAMES.items():
        if isinstance(v, t):
            return name
    return "other"


def _match_op(vals: list[Any], op: str, arg: Any, opts: dict) -> bool:
    present = [v for v in vals if v is not _MISSING]
    if op == "$eq":
        return any(_eq(v, arg) for v in vals)
    if op == "$ne":
        return not any(_eq(v, arg) for v in vals)
    if op in ("$gt", "$gte", "$lt", "$lte"):
        for v in present:
            if _type_rank(v) != _type_rank(arg) or v is None:
                continue
            c = _cmp(v, arg)
            if (
                (op == "$gt" and c > 0)
                or (op == "$gte" and c >= 0)
                or (op == "$lt" and c < 0)
                or (op == "$lte" and c <= 0)
            ):
                return True
        return False
    if op == "$in":
        return any(
            (
                _eq(v, a)
                if not isinstance(a, re.Pattern)
                else (isinstance(v, str) and a.search(v) is not None)
            )
            for v in vals
            for a in arg
        )
    if op == "$nin":
        return not _match_op(vals, "$in", arg, opts)
    if op == "$exists":
        return bool(present) == bool(arg)
    if op == "$regex":
        rx = _regex_of(arg, opts.get("$options", ""))
        return any(isinstance(v, str) and rx.search(v) is not None for v in vals)
    if op == "$options":
        return True  # consumed together with $regex
    if op == "$not":
        if isinstance(arg, re.Pattern):
            return not any(isinstance(v, str) and arg.search(v) is not None for v in vals)
        if isinstance(arg, dict):
            return not _match_ops(vals, arg)
        raise nope("$not with " + type(arg).__name__)
    if op == "$size":
        return any(isinstance(v, list) and len(v) == arg for v in present)
    raise nope(f"query operator {op}")


def _match_ops(vals: list[Any], ops: dict) -> bool:
    return all(_match_op(vals, op, arg, ops) for op, arg in ops.items())


def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, q) for q in cond):
                return False
        elif key == "$and":
            if not all(_match(doc, q) for q in cond):
                return False
        elif key == "$nor":
            if any(_match(doc, q) for q in cond):
                return False
        elif key == "$expr":
            if not _truthy(_expr(cond, doc)):
                return False
        elif key.startswith("$"):
            raise nope(f"top-level query operator {key}")
        else:
            vals = _candidates(doc, key)
            if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
                if not _match_ops(vals, cond):
                    return False
            elif isinstance(cond, re.Pattern):
                if not any(isinstance(v, str) and cond.search(v) is not None for v in vals):
                    return False
            elif not any(_eq(v, cond) for v in vals):
                return False
    return True


# ---------------------------------------------------------------- aggregation expressions
def _truthy(v: Any) -> bool:
    if v is None or v is _MISSING or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0
    return True


def _expr(e: Any, doc: dict) -> Any:
    if isinstance(e, str):
        if e.startswith("$$"):
            raise nope("system variables " + e)
        if e.startswith("$"):
            return _get(doc, e[1:])
        return e
    if isinstance(e, list):
        return [_expr(x, doc) for x in e]
    if not isinstance(e, dict):
        return e
    if len(e) == 1 and next(iter(e)).startswith("$"):
        op, arg = next(iter(e.items()))
        return _expr_op(op, arg, doc)
    return {k: _expr(v, doc) for k, v in e.items()}


def _val(v: Any) -> Any:
    return None if v is _MISSING else v


def _expr_op(op: str, arg: Any, doc: dict) -> Any:
    if op == "$cond":
        if isinstance(arg, list):
            c, t, f = arg
        else:
            c, t, f = arg["if"], arg["then"], arg["else"]
        return _expr(t, doc) if _truthy(_expr(c, doc)) else _expr(f, doc)
    if op in ("$eq", "$ne", "$gte", "$lt", "$gt", "$lte"):
        a, b = (_val(_expr(x, doc)) for x in arg)
        c = _cmp(a, b)
        return {
            "$eq": c == 0 and _type_rank(a) == _type_rank(b),
            "$ne": not (c == 0 and _type_rank(a) == _type_rank(b)),
            "$gte": c >= 0,
            "$lt": c < 0,
            "$gt": c > 0,
            "$lte": c <= 0,
        }[op]
    if op == "$and":
        return all(_truthy(_expr(x, doc)) for x in arg)
    if op == "$or":
        return any(_truthy(_expr(x, doc)) for x in arg)
    if op == "$type":
        return _type_name(_expr(arg, doc))
    if op == "$ifNull":
        for x in arg[:-1]:
            v = _expr(x, doc)
            if v is not None and v is not _MISSING:
                return v
        return _expr(arg[-1], doc)
    if op == "$concat":
        parts = [_expr(x, doc) for x in arg]
        if any(p is None or p is _MISSING for p in parts):
            return None
        return "".join(parts)
    if op == "$substrCP":
        s, start, n = (_expr(x, doc) for x in arg)
        return ("" if s in (None, _MISSING) else str(s))[start : start + n]
    if op == "$regexMatch":
        text = _expr(arg["input"], doc)
        rx = _regex_of(arg["regex"], arg.get("options", ""))
        return isinstance(text, str) and rx.search(text) is not None
    if op == "$dateToString":
        d = _expr(arg["date"], doc)
        if not isinstance(d, _dt.datetime):
            return None
        tz = arg.get("timezone")
        if tz:
            m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", tz)
            if not m:
                raise nope(f"$dateToString timezone {tz!r}")
            off = _dt.timedelta(hours=int(m[2]), minutes=int(m[3])) * (1 if m[1] == "+" else -1)
            d = _norm_dt(d).astimezone(_dt.timezone(off))
        fmt = arg.get("format", "%Y-%m-%dT%H:%M:%S.%LZ")
        if "%L" in fmt:
            raise nope("$dateToString format %L")
        return d.strftime(fmt)
    if op == "$sum":
        v = _expr(arg, doc)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    raise nope(f"aggregation expression {op}")


def _acc_init(spec: Any) -> tuple[str, Any]:
    if not (isinstance(spec, dict) and len(spec) == 1):
        raise nope("accumulator spec " + repr(spec))
    op, arg = next(iter(spec.items()))
    if op not in ("$sum", "$max"):
        raise nope(f"accumulator {op}")
    return op, arg


def _run_pipeline(docs: list[dict], pipeline: list[dict], collation_ci: bool) -> list[dict]:
    out = docs
    for stage in pipeline:
        if len(stage) != 1:
            raise nope("multi-key pipeline stage")
        name, arg = next(iter(stage.items()))
        if name == "$match":
            out = [d for d in out if _match(d, arg)]
        elif name == "$group":
            groups: dict[Any, dict] = {}
            order: list[Any] = []
            for d in out:
                gid = _val(_expr(arg["_id"], d))
                key = (
                    repr(gid)
                    if not isinstance(gid, (str, int, float, bool, type(None), ObjectId))
                    else (type(gid).__name__, gid)
                )
                if key not in groups:
                    groups[key] = {"_id": gid}
                    order.append(key)
                g = groups[key]
                for field, spec in arg.items():
                    if field == "_id":
                        continue
                    op, a = _acc_init(spec)
                    v = _val(_expr(a, d))
                    if op == "$sum":
                        g[field] = g.get(field, 0) + (
                            v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
                        )
                    else:  # $max
                        if v is not None and (
                            field not in g or g[field] is None or _cmp(v, g[field]) > 0
                        ):
                            g[field] = v
                        else:
                            g.setdefault(field, None)
            out = [groups[k] for k in order]
        elif name == "$sort":
            for key, direction in reversed(list(arg.items())):
                out = sorted(
                    out,
                    key=_KeyWrap(_path_getter(key), collation_ci),
                    reverse=direction < 0,
                )
        elif name == "$skip":
            out = out[arg:]
        elif name == "$limit":
            out = out[:arg]
        elif name == "$addFields":
            new = []
            for d in out:
                nd = copy.deepcopy(d)
                for k, e in arg.items():
                    _set_path(nd, k, _val(_expr(e, d)))
                new.append(nd)
            out = new
        elif name == "$project":
            if not all(v in (0, False) for v in arg.values()):
                raise nope("$project with inclusion")
            new = []
            for d in out:
                nd = copy.deepcopy(d)
                for k in arg:
                    _unset_path(nd, k)
                new.append(nd)
            out = new
        elif name == "$count":
            out = [{arg: len(out)}] if out else []
        elif name == "$facet":
            out = [
                {k: _run_pipeline(copy.deepcopy(out), sub, collation_ci) for k, sub in arg.items()}
            ]
        else:
            raise nope(f"aggregation stage {name}")
    return out


def _path_getter(path: str) -> Callable[[dict], Any]:
    def getter(doc: dict) -> Any:
        return _get(doc, path)

    return getter


class _SortKey:
    __slots__ = ("v", "ci")

    def __init__(self, v: Any, ci: bool) -> None:
        self.v, self.ci = v, ci

    def __lt__(self, other: _SortKey) -> bool:
        return _cmp(self.v, other.v, self.ci) < 0


class _KeyWrap:
    def __init__(self, getter: Callable[[dict], Any], ci: bool = False) -> None:
        self.getter, self.ci = getter, ci

    def __call__(self, doc: dict) -> _SortKey:
        return _SortKey(self.getter(doc), self.ci)


# ---------------------------------------------------------------- results
class InsertOneResult:
    def __init__(self, inserted_id: Any) -> None:
        self.inserted_id, self.acknowledged = inserted_id, True


class InsertManyResult:
    def __init__(self, ids: list[Any]) -> None:
        self.inserted_ids, self.acknowledged = ids, True


class UpdateResult:
    def __init__(self, matched: int, modified: int, upserted: Any = None) -> None:
        self.matched_count, self.modified_count, self.upserted_id, self.acknowledged = (
            matched,
            modified,
            upserted,
            True,
        )


class DeleteResult:
    def __init__(self, n: int) -> None:
        self.deleted_count, self.acknowledged = n, True


# ---------------------------------------------------------------- the collection core (sync)
class _Core:
    def __init__(self, dbname: str, name: str, tz_aware: bool) -> None:
        self.dbname, self.name, self.tz_aware = dbname, name, tz_aware

    @property
    def data(self) -> _CollData:
        """The collection's data for READING. Reading never creates the collection (real Mongo
        only creates it on the first write, create_index or create_collection)."""
        with _LOCK:
            return _STORE.get(self.dbname, {}).get(self.name) or _CollData()

    def _ensure(self) -> _CollData:
        with _LOCK:
            return _STORE.setdefault(self.dbname, {}).setdefault(self.name, _CollData())

    # -- helpers
    def _out(self, doc: dict | None, projection: Any = None) -> dict | None:
        if doc is None:
            return None
        d = _clean_out(doc, self.tz_aware)
        if projection:
            incl = {k for k, v in projection.items() if v and k != "_id"}
            excl = {k for k, v in projection.items() if not v}
            if incl:
                d = {
                    k: v
                    for k, v in d.items()
                    if k in incl or (k == "_id" and projection.get("_id", 1))
                }
            else:
                d = {k: v for k, v in d.items() if k not in excl}
        return d

    def _unique_check(self, doc: dict, skip_id: Any = _MISSING) -> None:
        for idx in self.data.indexes.values():
            if not idx.get("unique"):
                continue
            pf = idx.get("partialFilterExpression")
            if pf and not _match(doc, pf):
                continue
            keys = [k for k, _ in idx["key"]]
            vals = [_get(doc, k) for k in keys]
            if idx.get("sparse") and all(v is _MISSING for v in vals):
                continue
            for other in self.data.docs.values():
                if skip_id is not _MISSING and other["_id"] == skip_id:
                    continue
                if pf and not _match(other, pf):
                    continue
                if all(_eq(_get(other, k), v) for k, v in zip(keys, vals, strict=True)):
                    raise DuplicateKeyError(
                        f"E11000 duplicate key error collection: {self.dbname}.{self.name} index: {idx['name']} dup key: {vals}"
                    )

    def _store(self, doc: dict) -> Any:
        d = _clean_in(doc)
        d.setdefault("_id", ObjectId())
        with _LOCK:
            coll = self._ensure()
            if d["_id"] in coll.docs:
                raise DuplicateKeyError(
                    f"E11000 duplicate key error collection: {self.dbname}.{self.name} index: _id_ dup key: {{ _id: {d['_id']!r} }}"
                )
            self._unique_check(d)
            coll.docs[d["_id"]] = d
        return d["_id"]

    def _matching(self, flt: dict | None) -> list[dict]:
        flt = flt or {}
        return [d for d in list(self.data.docs.values()) if _match(d, flt)]

    # -- writes
    def insert_one(self, doc: dict) -> InsertOneResult:
        with _LOCK:
            _id = self._store(doc)
        if "_id" not in doc:
            doc["_id"] = _id  # real drivers add the generated _id to the caller's dict
        return InsertOneResult(_id)

    def insert_many(self, docs: list[dict], ordered: bool = True) -> InsertManyResult:
        ids = []
        with _LOCK:
            for d in docs:
                _id = self._store(d)
                if "_id" not in d:
                    d["_id"] = _id
                ids.append(_id)
        return InsertManyResult(ids)

    def _apply(self, doc: dict, update: dict, inserting: bool) -> dict:
        if not update or not all(k.startswith("$") for k in update):
            raise nope("replacement-style update (an update needs $operators)")
        new = copy.deepcopy(doc)
        for op, spec in update.items():
            if op == "$set":
                for k, v in spec.items():
                    _set_path(new, k, _clean_in(v))
            elif op == "$unset":
                for k in spec:
                    _unset_path(new, k)
            elif op == "$inc":
                for k, v in spec.items():
                    cur = _get(new, k)
                    _set_path(new, k, (0 if cur is _MISSING or cur is None else cur) + v)
            elif op == "$setOnInsert":
                if inserting:
                    for k, v in spec.items():
                        _set_path(new, k, _clean_in(v))
            else:
                raise nope(f"update operator {op}")
        return new

    def _upsert_base(self, flt: dict) -> dict:
        base: dict = {}
        for k, v in (flt or {}).items():
            if k.startswith("$"):
                continue
            if isinstance(v, dict) and v and all(x.startswith("$") for x in v):
                if "$eq" in v:
                    _set_path(base, k, copy.deepcopy(v["$eq"]))
                continue
            if isinstance(v, re.Pattern):
                continue
            _set_path(base, k, copy.deepcopy(v))
        return base

    def _update(
        self, flt: dict, update: dict, upsert: bool, many: bool, sort: Any = None
    ) -> tuple[UpdateResult, dict | None, dict | None]:
        with _LOCK:
            found = self._matching(flt)
            if sort and found:
                found = self._sorted(found, sort)
            if not found:
                if not upsert:
                    return UpdateResult(0, 0), None, None
                base = self._upsert_base(flt)
                new = self._apply(base, update, True)
                _id = self._store(new)
                return UpdateResult(0, 0, _id), None, copy.deepcopy(self.data.docs[_id])
            targets = found if many else found[:1]
            modified, first_before, first_after = 0, None, None
            for d in targets:
                new = self._apply(d, update, False)
                new = _clean_in(new)
                if new["_id"] != d["_id"]:
                    raise OperationFailure(
                        "Performing an update on the path '_id' would modify the immutable field '_id'"
                    )
                self._unique_check(new, skip_id=d["_id"])
                changed = new != d
                if first_before is None:
                    first_before, first_after = copy.deepcopy(d), copy.deepcopy(new)
                if changed:
                    modified += 1
                    self.data.docs[d["_id"]] = new
            return UpdateResult(len(targets), modified), first_before, first_after

    def update_one(self, flt: dict, update: dict, upsert: bool = False, **kw: Any) -> UpdateResult:
        if kw:
            raise nope(f"update_one options {sorted(kw)}")
        return self._update(flt, update, upsert, False)[0]

    def update_many(self, flt: dict, update: dict, upsert: bool = False, **kw: Any) -> UpdateResult:
        if kw:
            raise nope(f"update_many options {sorted(kw)}")
        return self._update(flt, update, upsert, True)[0]

    def find_one_and_update(
        self,
        flt: dict,
        update: dict,
        projection: Any = None,
        sort: Any = None,
        upsert: bool = False,
        return_document: bool = ReturnDocument.BEFORE,
        **kw: Any,
    ) -> dict | None:
        if kw:
            raise nope(f"find_one_and_update options {sorted(kw)}")
        _, before, after = self._update(flt, update, upsert, False, sort)
        return self._out(after if return_document == ReturnDocument.AFTER else before, projection)

    def delete_one(self, flt: dict) -> DeleteResult:
        with _LOCK:
            found = self._matching(flt)[:1]
            for d in found:
                del self.data.docs[d["_id"]]
        return DeleteResult(len(found))

    def delete_many(self, flt: dict | None = None) -> DeleteResult:
        with _LOCK:
            found = self._matching(flt)
            for d in found:
                del self.data.docs[d["_id"]]
        return DeleteResult(len(found))

    # -- reads
    def _sorted(self, docs: list[dict], sort: Any, ci: bool = False) -> list[dict]:
        keys = (
            [(sort, 1)]
            if isinstance(sort, str)
            else list(sort.items()) if isinstance(sort, dict) else list(sort)
        )
        out = docs
        for key, direction in reversed(keys):
            out = sorted(out, key=_KeyWrap(_path_getter(key), ci), reverse=direction < 0)
        return out

    def find_one(
        self, flt: dict | None = None, projection: Any = None, sort: Any = None, **kw: Any
    ) -> dict | None:
        if kw:
            raise nope(f"find_one options {sorted(kw)}")
        with _LOCK:
            docs = self._matching(flt)
            if sort and docs:
                docs = self._sorted(docs, sort)
            return self._out(docs[0], projection) if docs else None

    def find(self, flt: dict | None = None, projection: Any = None, **kw: Any) -> _CursorCore:
        if kw:
            raise nope(f"find options {sorted(kw)}")
        return _CursorCore(self, flt or {}, projection)

    def count_documents(self, flt: dict | None = None, **kw: Any) -> int:
        if kw:
            raise nope(f"count_documents options {sorted(kw)}")
        with _LOCK:
            return len(self._matching(flt))

    def estimated_document_count(self) -> int:
        with _LOCK:
            return len(self.data.docs)

    def distinct(self, key: str, flt: dict | None = None) -> list[Any]:
        seen: list[Any] = []
        with _LOCK:
            for d in self._matching(flt):
                v = _get(d, key)
                for x in (v if isinstance(v, list) else [v]):
                    if x is not _MISSING and not any(_eq(x, s) for s in seen):
                        seen.append(_clean_out(x, self.tz_aware))
        return seen

    def aggregate(
        self, pipeline: list[dict], allowDiskUse: bool = False, collation: Any = None, **kw: Any
    ) -> list[dict]:  # noqa: N803
        if kw:
            raise nope(f"aggregate options {sorted(kw)}")
        strength = (
            getattr(collation, "document", {}).get("strength", 3) if collation is not None else 3
        )
        with _LOCK:
            docs = [copy.deepcopy(d) for d in self.data.docs.values()]
        res = _run_pipeline(docs, pipeline, collation is not None and strength < 3)
        return [_clean_out(d, self.tz_aware) for d in res]

    # -- indexes
    def create_index(self, keys: Any, **opts: Any) -> str:
        key = [(keys, 1)] if isinstance(keys, str) else [(k, d) for k, d in keys]
        name = opts.pop("name", None) or "_".join(f"{k}_{d}" for k, d in key)
        allowed = {
            "unique",
            "sparse",
            "expireAfterSeconds",
            "partialFilterExpression",
            "background",
        }
        if set(opts) - allowed:
            raise nope(f"create_index options {sorted(set(opts) - allowed)}")
        spec = {"key": key, "name": name, **{k: v for k, v in opts.items() if k != "background"}}
        with _LOCK:
            coll = self._ensure()
            cur = coll.indexes.get(name)
            if cur is not None:
                if {k: v for k, v in cur.items()} != spec:
                    raise OperationFailure(
                        f"Index already exists with a different definition: {name}"
                    )
                return name
            for other in self.data.indexes.values():
                if other["key"] == key and {k: v for k, v in other.items() if k != "name"} != {
                    k: v for k, v in spec.items() if k != "name"
                }:
                    raise OperationFailure(
                        f"Index already exists with a different name or options for the same key: {other['name']}"
                    )
                if other["key"] == key:
                    return other["name"]
            if spec.get(
                "unique"
            ):  # an existing duplicate must make the build fail, like real Mongo
                seen: list[Any] = []
                for d in self.data.docs.values():
                    pf = spec.get("partialFilterExpression")
                    if pf and not _match(d, pf):
                        continue
                    vals = [_get(d, k) for k, _ in key]
                    if spec.get("sparse") and all(v is _MISSING for v in vals):
                        continue
                    if any(all(_eq(a, b) for a, b in zip(vals, s, strict=True)) for s in seen):
                        raise DuplicateKeyError(f"E11000 duplicate key error building index {name}")
                    seen.append(vals)
            coll.indexes[name] = spec
        return name

    def drop_index(self, name: str) -> None:
        with _LOCK:
            if name not in self.data.indexes or name == "_id_":
                raise OperationFailure(f"index not found with name [{name}]")
            del self.data.indexes[name]

    def list_indexes_docs(self) -> list[dict]:
        with _LOCK:
            return [
                {"v": 2, **copy.deepcopy(i), "key": {k: d for k, d in i["key"]}}
                for i in self.data.indexes.values()
            ]

    def index_information(self) -> dict:
        with _LOCK:
            return {
                n: {
                    "key": list(i["key"]),
                    **{k: v for k, v in i.items() if k not in ("key", "name")},
                }
                for n, i in self.data.indexes.items()
            }

    def drop(self) -> None:
        with _LOCK:
            _STORE.get(self.dbname, {}).pop(self.name, None)


class _CursorCore:
    def __init__(self, core: _Core, flt: dict, projection: Any) -> None:
        self.core, self.flt, self.projection = core, flt, projection
        self._sort: Any = None
        self._skip = 0
        self._limit = 0

    def sort(self, key: Any, direction: int | None = None) -> _CursorCore:
        self._sort = (
            [(key, direction if direction is not None else 1)]
            if isinstance(key, str)
            else list(key)
        )
        return self

    def skip(self, n: int) -> _CursorCore:
        self._skip = n
        return self

    def limit(self, n: int) -> _CursorCore:
        self._limit = n
        return self

    def collation(self, *_a: Any, **_k: Any) -> _CursorCore:
        raise nope("cursor.collation")

    def hint(self, *_a: Any, **_k: Any) -> _CursorCore:
        raise nope("cursor.hint")

    def _all(self) -> list[dict]:
        with _LOCK:
            docs = self.core._matching(self.flt)
            if self._sort:
                docs = self.core._sorted(docs, self._sort)
            docs = docs[self._skip :]
            if self._limit:
                docs = docs[: abs(self._limit)]
            return [self.core._out(d, self.projection) for d in docs]  # type: ignore[misc]


# ---------------------------------------------------------------- async (PyMongo Async) API
class _AsyncCursor:
    def __init__(self, items: Callable[[], list[dict]]) -> None:
        self._items = items
        self._it: Any = None

    def __aiter__(self) -> _AsyncCursor:
        self._it = None  # the query runs on the first __anext__, after one yield (a real fetch)
        return self

    async def __anext__(self) -> dict:
        if self._it is None:
            await _yield()
            self._it = iter(self._items())
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def to_list(self, length: int | None = None) -> list[dict]:
        await _yield()
        items = self._items()
        return items if length is None else items[:length]


class _FindCursor(_AsyncCursor):
    def __init__(self, core: _CursorCore) -> None:
        super().__init__(core._all)
        self._c = core

    def sort(self, key: Any, direction: int | None = None) -> _FindCursor:
        self._c.sort(key, direction)
        return self

    def skip(self, n: int) -> _FindCursor:
        self._c.skip(n)
        return self

    def limit(self, n: int) -> _FindCursor:
        self._c.limit(n)
        return self

    def collation(self, *a: Any, **k: Any) -> _FindCursor:
        self._c.collation(*a, **k)
        return self

    def hint(self, *a: Any, **k: Any) -> _FindCursor:
        self._c.hint(*a, **k)
        return self


class _AsyncCollection:
    _PASS = (
        "insert_one",
        "insert_many",
        "find_one",
        "count_documents",
        "estimated_document_count",
        "update_one",
        "update_many",
        "delete_one",
        "delete_many",
        "find_one_and_update",
        "distinct",
        "create_index",
        "drop_index",
        "drop",
    )

    def __init__(self, db: Any, name: str) -> None:
        self.database, self.name = db, name
        self._core = _Core(db.name, name, db.client.tz_aware)

    @property
    def full_name(self) -> str:
        return f"{self.database.name}.{self.name}"

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        raise nope(f"collection.{item}")

    def find(self, *a: Any, **k: Any) -> _FindCursor:
        return _FindCursor(self._core.find(*a, **k))

    # Unlike Motor, PyMongo Async's aggregate() and list_indexes() are coroutines: the command runs
    # when awaited (so an unsupported stage fails there, like OperationFailure on a real server)
    # and the awaited result is the cursor.
    async def aggregate(self, pipeline: list[dict], **k: Any) -> _AsyncCursor:
        await _yield()
        items = self._core.aggregate(pipeline, **k)
        return _AsyncCursor(lambda: items)

    async def list_indexes(self) -> _AsyncCursor:
        await _yield()
        items = self._core.list_indexes_docs()
        return _AsyncCursor(lambda: items)


def _make_async_method(name: str) -> Callable[..., Any]:
    async def call(self: _AsyncCollection, *a: Any, **k: Any) -> Any:
        await _yield()
        return getattr(self._core, name)(*a, **k)

    call.__name__ = name
    return call


# Real class attributes (like Motor's), so tests can monkeypatch them on the class.
for _name in _AsyncCollection._PASS:
    setattr(_AsyncCollection, _name, _make_async_method(_name))


class _AsyncDatabase:
    def __init__(self, client: Any, name: str) -> None:
        self.client, self.name = client, name

    def __getitem__(self, coll: str) -> _AsyncCollection:
        return _AsyncCollection(self, coll)

    def __getattr__(self, coll: str) -> _AsyncCollection:
        if coll.startswith("_"):
            raise AttributeError(coll)
        return _AsyncCollection(self, coll)

    async def list_collection_names(self, *a: Any, **k: Any) -> list[str]:
        await _yield()
        with _LOCK:
            return list(_STORE.get(self.name, {}))

    async def create_collection(self, name: str, **k: Any) -> _AsyncCollection:
        await _yield()
        with _LOCK:
            _STORE.setdefault(self.name, {}).setdefault(name, _CollData())
        return self[name]

    async def drop_collection(self, name: str) -> None:
        await _yield()
        with _LOCK:
            _STORE.get(self.name, {}).pop(name, None)

    async def command(self, cmd: Any, *a: Any, **k: Any) -> dict:
        await _yield()
        if cmd == "ping" or cmd == {"ping": 1}:
            return {"ok": 1.0}
        raise nope(f"database.command({cmd!r})")


class _AsyncAdmin:
    async def command(self, cmd: Any, *a: Any, **k: Any) -> dict:
        await _yield()
        if cmd == "ping" or cmd == {"ping": 1}:
            return {"ok": 1.0}
        raise nope(f"admin.command({cmd!r})")


class FakeAsyncClient:
    """Stands in for pymongo.AsyncMongoClient."""

    def __init__(self, *_a: Any, tz_aware: bool = False, **_k: Any) -> None:
        self.tz_aware = tz_aware
        self.admin = _AsyncAdmin()

    def __getitem__(self, name: str) -> _AsyncDatabase:
        return _AsyncDatabase(self, name)

    async def list_database_names(self) -> list[str]:
        await _yield()
        with _LOCK:
            return list(_STORE)

    async def drop_database(self, name: str) -> None:
        await _yield()
        with _LOCK:
            _STORE.pop(name, None)

    async def close(self) -> None:  # PyMongo Async: close() is a coroutine (Motor's was sync)
        await _yield()


# ---------------------------------------------------------------- sync (PyMongo) API
class _SyncCollection:
    def __init__(self, db: Any, name: str) -> None:
        self.database, self.name = db, name
        self._core = _Core(db.name, name, db.client.tz_aware)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        core = self._core
        if item in _AsyncCollection._PASS or item in ("index_information",):
            return getattr(core, item)
        raise nope(f"sync collection.{item}")

    def find(self, *a: Any, **k: Any) -> Any:
        return _SyncCursor(self._core.find(*a, **k))

    def aggregate(self, pipeline: list[dict], **k: Any) -> Any:
        return iter(self._core.aggregate(pipeline, **k))

    def list_indexes(self) -> Any:
        return iter(self._core.list_indexes_docs())


class _SyncCursor(_CursorCore):
    def __init__(self, core: _CursorCore) -> None:
        self.__dict__.update(core.__dict__)

    def __iter__(self) -> Any:
        return iter(self._all())


class _SyncDatabase:
    def __init__(self, client: Any, name: str) -> None:
        self.client, self.name = client, name

    def __getitem__(self, coll: str) -> _SyncCollection:
        return _SyncCollection(self, coll)

    def __getattr__(self, coll: str) -> _SyncCollection:
        if coll.startswith("_"):
            raise AttributeError(coll)
        return _SyncCollection(self, coll)

    def list_collection_names(self) -> list[str]:
        with _LOCK:
            return list(_STORE.get(self.name, {}))


class FakeSyncClient:
    """Stands in for pymongo.MongoClient."""

    def __init__(self, *_a: Any, tz_aware: bool = False, **_k: Any) -> None:
        self.tz_aware = tz_aware

    def __getitem__(self, name: str) -> _SyncDatabase:
        return _SyncDatabase(self, name)

    def list_database_names(self) -> list[str]:
        with _LOCK:
            return list(_STORE)

    def drop_database(self, name: str) -> None:
        with _LOCK:
            _STORE.pop(name, None)

    def close(self) -> None:
        return None


# ---------------------------------------------------------------- GridFS
class FakeGridIn:
    def __init__(self, bucket: FakeGridFSBucket, filename: str, metadata: dict | None) -> None:
        self._bucket, self._filename, self._metadata = bucket, filename, metadata
        self._id = ObjectId()
        self._buf = bytearray()
        self._closed = False

    async def write(self, data: bytes) -> None:
        await _yield()
        if self._closed:
            raise ValueError("cannot write to a closed GridIn")
        self._buf.extend(data)

    async def close(self) -> None:
        if self._closed:
            return
        await _yield()
        self._closed = True
        files, chunks = self._bucket._files, self._bucket._chunks
        data = bytes(self._buf)
        for n, i in enumerate(range(0, len(data), _CHUNK)):
            chunks.insert_one(
                {"_id": ObjectId(), "files_id": self._id, "n": n, "data": data[i : i + _CHUNK]}
            )
        doc = {
            "_id": self._id,
            "length": len(data),
            "chunkSize": _CHUNK,
            "uploadDate": _dt.datetime.now(_dt.timezone.utc),
            "filename": self._filename,
        }
        if self._metadata is not None:
            doc["metadata"] = self._metadata
        files.insert_one(doc)

    async def __aenter__(self) -> FakeGridIn:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


class FakeGridOut:
    def __init__(self, doc: dict, data: bytes) -> None:
        self._id, self.length, self.filename, self.metadata = (
            doc["_id"],
            doc["length"],
            doc.get("filename"),
            doc.get("metadata"),
        )
        self._data, self._pos = data, 0

    async def read(self, size: int = -1) -> bytes:
        await _yield()
        end = len(self._data) if size is None or size < 0 else self._pos + size
        out = self._data[self._pos : end]
        self._pos = min(end, len(self._data))
        return out


class FakeGridFSBucket:
    """Stands in for gridfs.asynchronous.AsyncGridFSBucket (bucket "fs" -> fs.files / fs.chunks)."""

    def __init__(self, db: _AsyncDatabase, bucket_name: str = "fs", **kw: Any) -> None:
        if kw:
            raise nope(f"GridFSBucket options {sorted(kw)}")
        self._db, self._bucket = db, bucket_name
        self._files = _Core(db.name, f"{bucket_name}.files", db.client.tz_aware)
        self._chunks = _Core(db.name, f"{bucket_name}.chunks", db.client.tz_aware)

    def open_upload_stream(
        self,
        filename: str,
        chunk_size_bytes: int | None = None,
        metadata: dict | None = None,
        **kw: Any,
    ) -> FakeGridIn:
        if kw or chunk_size_bytes is not None:
            raise nope("open_upload_stream options")
        return FakeGridIn(self, filename, metadata)

    async def upload_from_stream(
        self,
        filename: str,
        source: Any,
        chunk_size_bytes: int | None = None,
        metadata: dict | None = None,
        **kw: Any,
    ) -> ObjectId:
        if kw or chunk_size_bytes is not None:
            raise nope("upload_from_stream options")
        grid_in = FakeGridIn(self, filename, metadata)
        await grid_in.write(
            bytes(source) if isinstance(source, (bytes, bytearray)) else source.read()
        )
        await grid_in.close()
        return grid_in._id

    async def open_download_stream(self, file_id: Any) -> FakeGridOut:
        await _yield()
        doc = self._files.find_one({"_id": file_id})
        if doc is None:
            raise NoFile(f"no file in gridfs collection {self._bucket}.files with _id {file_id!r}")
        chunks = sorted(self._chunks.find({"files_id": file_id})._all(), key=lambda c: c["n"])
        return FakeGridOut(doc, b"".join(c["data"] for c in chunks))

    async def delete(self, file_id: Any) -> None:
        await _yield()
        res = self._files.delete_one({"_id": file_id})
        self._chunks.delete_many({"files_id": file_id})
        if res.deleted_count == 0:
            raise NoFile(f"no file in gridfs collection {self._bucket}.files with _id {file_id!r}")

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        raise nope(f"GridFSBucket.{item}")
