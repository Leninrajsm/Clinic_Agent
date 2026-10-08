"""Minimal document-store interface with MongoDB and in-memory implementations.

The clinic repository is written once against this interface, so the agent, harness and
loop behave identically whether a reviewer runs against Atlas or with no database at all.
"""

import copy
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)

Filter = dict[str, Any]
Sort = list[tuple[str, int]]


class DocumentStore(Protocol):
    backend: str

    async def insert_one(self, coll: str, doc: dict) -> None: ...
    async def insert_many(self, coll: str, docs: list[dict]) -> None: ...
    async def find(self, coll: str, flt: Filter, sort: Sort | None = None, limit: int = 0) -> list[dict]: ...
    async def find_one(self, coll: str, flt: Filter) -> dict | None: ...
    async def update_one(self, coll: str, flt: Filter, set_fields: dict) -> bool: ...
    async def delete_many(self, coll: str, flt: Filter) -> int: ...
    async def count(self, coll: str, flt: Filter) -> int: ...


# ---------------------------------------------------------------- in-memory

def _matches(doc: dict, flt: Filter) -> bool:
    for key, cond in flt.items():
        val = doc.get(key)
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$in" and val not in arg:
                    return False
                if op == "$nin" and val in arg:
                    return False
                if op == "$ne" and val == arg:
                    return False
                if val is None and op in ("$gt", "$gte", "$lt", "$lte"):
                    return False
                if op == "$gt" and not val > arg:
                    return False
                if op == "$gte" and not val >= arg:
                    return False
                if op == "$lt" and not val < arg:
                    return False
                if op == "$lte" and not val <= arg:
                    return False
        elif val != cond:
            return False
    return True


class MemoryStore:
    """Single-process store. asyncio is single-threaded, so check-and-set in update_one is atomic."""

    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}

    def _coll(self, coll: str) -> list[dict]:
        return self._data.setdefault(coll, [])

    async def insert_one(self, coll: str, doc: dict) -> None:
        self._coll(coll).append(copy.deepcopy(doc))

    async def insert_many(self, coll: str, docs: list[dict]) -> None:
        self._coll(coll).extend(copy.deepcopy(d) for d in docs)

    async def find(self, coll: str, flt: Filter, sort: Sort | None = None, limit: int = 0) -> list[dict]:
        rows = [d for d in self._coll(coll) if _matches(d, flt)]
        for field, direction in reversed(sort or []):
            rows.sort(key=lambda d: d.get(field), reverse=direction < 0)
        if limit:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    async def find_one(self, coll: str, flt: Filter) -> dict | None:
        for d in self._coll(coll):
            if _matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def update_one(self, coll: str, flt: Filter, set_fields: dict) -> bool:
        for d in self._coll(coll):
            if _matches(d, flt):
                d.update(copy.deepcopy(set_fields))
                return True
        return False

    async def delete_many(self, coll: str, flt: Filter) -> int:
        rows = self._coll(coll)
        keep = [d for d in rows if not _matches(d, flt)]
        self._data[coll] = keep
        return len(rows) - len(keep)

    async def count(self, coll: str, flt: Filter) -> int:
        return sum(1 for d in self._coll(coll) if _matches(d, flt))


# ---------------------------------------------------------------- MongoDB

INDEXES: dict[str, list[list[tuple[str, int]]]] = {
    "patients": [[("sandbox_id", 1), ("last_name", 1)]],
    "providers": [[("sandbox_id", 1), ("id", 1)]],
    "slots": [[("sandbox_id", 1), ("id", 1)], [("sandbox_id", 1), ("specialty", 1), ("start", 1)]],
    "appointments": [[("sandbox_id", 1), ("patient_id", 1)]],
    "sessions": [[("id", 1)]],
    "audit_log": [[("session_id", 1), ("seq", 1)]],
    "escalations": [[("sandbox_id", 1)]],
}


class MongoStore:
    backend = "mongodb"

    def __init__(self, uri: str, db_name: str):
        from pymongo import AsyncMongoClient

        self._client = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=6000)
        self._db = self._client[db_name]

    async def connect(self) -> None:
        await self._client.admin.command("ping")
        try:
            for coll, specs in INDEXES.items():
                for spec in specs:
                    await self._db[coll].create_index(spec)
        except Exception as exc:  # read-only users cannot create indexes; that's fine
            log.info("Skipping index creation: %s", exc)

    async def insert_one(self, coll: str, doc: dict) -> None:
        await self._db[coll].insert_one(dict(doc))

    async def insert_many(self, coll: str, docs: list[dict]) -> None:
        if docs:
            await self._db[coll].insert_many([dict(d) for d in docs])

    async def find(self, coll: str, flt: Filter, sort: Sort | None = None, limit: int = 0) -> list[dict]:
        cursor = self._db[coll].find(flt, {"_id": 0})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def find_one(self, coll: str, flt: Filter) -> dict | None:
        return await self._db[coll].find_one(flt, {"_id": 0})

    async def update_one(self, coll: str, flt: Filter, set_fields: dict) -> bool:
        res = await self._db[coll].update_one(flt, {"$set": set_fields})
        return res.matched_count > 0

    async def delete_many(self, coll: str, flt: Filter) -> int:
        res = await self._db[coll].delete_many(flt)
        return res.deleted_count

    async def count(self, coll: str, flt: Filter) -> int:
        return await self._db[coll].count_documents(flt)


async def open_store(mongodb_uri: str, db_name: str) -> DocumentStore:
    """Use Atlas when configured and reachable; otherwise fall back to memory (and say so)."""
    if not mongodb_uri:
        log.warning("MONGODB_URI not set: using the in-memory database.")
        return MemoryStore()
    try:
        store = MongoStore(mongodb_uri, db_name)
        await store.connect()
        return store
    except Exception as exc:
        log.warning("MongoDB not reachable (%s): falling back to the in-memory database.", exc)
        return MemoryStore()
