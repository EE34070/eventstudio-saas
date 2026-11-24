"""Dépôt « tenant-aware » : SEULE porte d'accès des modules métier à MongoDB.

- La base utilisée est celle de la société active (ctx.db) : les données des autres
  sociétés ne sont pas dans la même base.
- org_id est AUSSI injecté dans chaque document et filtre (double sécurité, et permet
  de déplacer une société d'un cluster à l'autre) ; il ne vient jamais du client.
- Tentative de filtrer sur un autre org_id → erreur (bug ou attaque, dans les deux cas on bloque).
- Suppression = mise en corbeille (deleted_at), purge définitive par tâche planifiée.
- Toute écriture alimente le journal d'audit.
"""
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from .db import PLATFORM_COLLECTIONS
from .tenancy import TenantContext

PROTECTED_FIELDS = {"_id", "org_id", "created_at", "created_by", "deleted_at"}


class TenantIsolationError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class TenantRepository:
    def __init__(self, ctx: TenantContext, collection: str):
        if collection in PLATFORM_COLLECTIONS:
            raise TenantIsolationError(f"{collection} est une collection plateforme")
        if ctx.db is None:
            raise TenantIsolationError("Aucune base société dans le contexte")
        db = ctx.db
        if db.name != f"t_{ctx.org_id}" and not (ctx.org.get("db") or {}).get("name") == db.name:
            raise TenantIsolationError("La base ne correspond pas à la société active")
        self.db = db
        self.col = db[collection]
        self.name = collection
        self.ctx = ctx

    # --- filtres -------------------------------------------------------------
    def _scope(self, flt: dict | None = None, include_deleted: bool = False) -> dict:
        flt = dict(flt or {})
        if "org_id" in flt and flt["org_id"] != self.ctx.org_id:
            raise TenantIsolationError("Filtre org_id étranger interdit")
        flt["org_id"] = self.ctx.org_id
        if not include_deleted:
            flt.setdefault("deleted_at", None)
        return flt

    @staticmethod
    def _clean(data: dict) -> dict:
        return {k: v for k, v in data.items() if k not in PROTECTED_FIELDS}

    # --- lecture -------------------------------------------------------------
    async def get(self, _id: str) -> dict | None:
        return await self.col.find_one(self._scope({"_id": _id}))

    async def find(self, flt: dict | None = None, *, sort=None, skip: int = 0, limit: int = 50) -> list[dict]:
        cur = self.col.find(self._scope(flt))
        if sort:
            cur = cur.sort(sort)
        return await cur.skip(skip).limit(min(limit, 500)).to_list(length=None)

    async def count(self, flt: dict | None = None) -> int:
        return await self.col.count_documents(self._scope(flt))

    # --- écriture ------------------------------------------------------------
    async def insert(self, data: dict) -> dict:
        doc = {
            **self._clean(data),
            "_id": data.get("_id") or uuid4().hex,
            "org_id": self.ctx.org_id,
            "created_at": _now(),
            "created_by": self.ctx.user_id,
            "updated_at": _now(),
            "deleted_at": None,
        }
        await self.col.insert_one(doc)
        await self._audit("create", doc["_id"])
        return doc

    async def update(self, _id: str, changes: dict) -> dict | None:
        changes = {**self._clean(changes), "updated_at": _now(), "updated_by": self.ctx.user_id}
        doc = await self.col.find_one_and_update(
            self._scope({"_id": _id}), {"$set": changes}, return_document=ReturnDocument.AFTER
        )
        if doc:
            await self._audit("update", _id, fields=sorted(changes))
        return doc

    async def soft_delete(self, _id: str) -> bool:
        res = await self.col.update_one(self._scope({"_id": _id}), {"$set": {"deleted_at": _now(), "deleted_by": self.ctx.user_id}})
        if res.modified_count:
            await self._audit("delete", _id)
        return bool(res.modified_count)

    async def restore(self, _id: str) -> bool:
        flt = self._scope({"_id": _id}, include_deleted=True)
        flt["deleted_at"] = {"$ne": None}
        res = await self.col.update_one(flt, {"$set": {"deleted_at": None}})
        return bool(res.modified_count)

    async def _audit(self, action: str, ref: str, **extra: Any) -> None:
        await self.db.audit_log.insert_one({
            "_id": uuid4().hex, "org_id": self.ctx.org_id, "user_id": self.ctx.user_id,
            "collection": self.name, "ref": ref, "action": action, "at": _now(), **extra,
        })
