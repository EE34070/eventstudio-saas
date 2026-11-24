"""Une base MongoDB par société, sans réécrire les routes existantes.

Le code historique utilise un objet global `db` (core.py) et filtre chaque requête par
org_id. Ce module remplace la base unique par un routage transparent :

    collections plateforme (PLATFORM)  -> base « platform » (CONTROL_DB)
    toutes les autres                  -> base de la société active : t_<org_id>

La société active vit dans une variable de contexte, posée :
  - à l'authentification (core.current_member)       -> épinglée pour toute la requête
  - à la construction d'un Ctx (core.Ctx)            -> si rien n'est épinglé
  - par for_each_org() pour les tâches planifiées    -> une passe épinglée par société
  - par la résolution d'un jeton de lien public      -> épinglée (devis, missions, DJ…)

Sans société active, une requête sur une collection métier est REFUSÉE
(TenantContextMissing) : on préfère une erreur visible à une lecture au mauvais endroit.

Liens publics : les empreintes de jeton (share_hash, token_hash, guest_token_hash) écrites
dans une base société sont indexées dans platform.link_index ; une lecture publique par
empreinte retrouve ainsi sa société.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("tenant_router")

# Collections de la base plateforme : jamais dans une base société.
PLATFORM = {
    "orgs",            # sociétés (+ emplacement de leur base : orgs.db)
    "users",           # comptes, rattachement à une société, rôle
    "module_defs",     # catalogue global des modules métier
    "job_locks",       # verrous des tâches planifiées (toutes instances)
    "webhook_events",  # anti-doublon des webhooks (Yousign, Gmail…)
    "link_index",      # empreinte de jeton public -> société
    "tenant_migrations",  # journal des migrations par société
    "cron_runs",       # anti-doublon des appels cron
    "oauth_states",    # état OAuth Google (porte org_id), lu au retour public
}
TOKEN_FIELDS = ("share_hash", "token_hash", "guest_token_hash", "ical_hash")
DB_ATTRS = {"command", "list_collection_names", "create_collection", "drop_collection", "get_collection",
            "name", "client", "aggregate", "watch", "with_options", "validate_collection", "dereference"}

_org: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_org", default=None)
_pinned: contextvars.ContextVar[bool] = contextvars.ContextVar("tenant_pinned", default=False)
_placements: dict[str, tuple[str, str]] = {}  # org_id -> (cluster, nom de base)


class TenantContextMissing(RuntimeError):
    pass


class TenantMismatch(PermissionError):
    pass


# --------------------------------------------------------------------------------------
# Clusters
# --------------------------------------------------------------------------------------
def tenant_db_name(org_id: str) -> str:
    name = "t_" + re.sub(r"[^a-zA-Z0-9]", "", org_id)
    if len(name) < 5 or len(name) > 60:
        raise ValueError("Identifiant de société invalide pour un nom de base")
    return name


class Clusters:
    def __init__(self, clients: dict[str, AsyncIOMotorClient], control_db: str):
        self.clients = clients
        self.control_db = control_db

    @classmethod
    def from_env(cls) -> "Clusters":
        uris = {"default": os.environ["MONGO_URL"], **json.loads(os.environ.get("TENANT_CLUSTERS") or "{}")}
        return cls({k: AsyncIOMotorClient(v, tz_aware=False) for k, v in uris.items()},
                   os.environ.get("CONTROL_DB") or os.environ.get("DB_NAME") or "platform")

    @property
    def control(self):
        return self.clients["default"][self.control_db]

    def tenant(self, org_id: str):
        cluster, name = _placements.get(org_id) or ("default", tenant_db_name(org_id))
        if cluster not in self.clients:
            raise RuntimeError(f"Cluster « {cluster} » non configuré (société {org_id})")
        if name == self.control_db:
            raise RuntimeError("Une société ne peut pas utiliser la base plateforme")
        return self.clients[cluster][name]

    def close(self) -> None:
        for c in self.clients.values():
            c.close()


CLUSTERS: Clusters | None = None


def init(clusters: Clusters) -> None:
    global CLUSTERS
    CLUSTERS = clusters
    _placements.clear()


def _c() -> Clusters:
    if CLUSTERS is None:
        raise RuntimeError("tenant_router.init() non appelé")
    return CLUSTERS


async def load_placements() -> int:
    """Charge l'annuaire orgs.db (clusters dédiés). À appeler au démarrage et après création."""
    n = 0
    async for o in _c().control.orgs.find({"db": {"$exists": True}}, {"_id": 0, "id": 1, "db": 1}):
        _placements[o["id"]] = (o["db"].get("cluster", "default"), o["db"].get("name") or tenant_db_name(o["id"]))
        n += 1
    return n


# --------------------------------------------------------------------------------------
# Société active
# --------------------------------------------------------------------------------------
def current_org() -> str | None:
    return _org.get()


def pin_org(org_id: str) -> None:
    """Épingle la société pour la suite de la requête / de la tâche. Refuse un changement."""
    cur = _org.get()
    if _pinned.get() and cur and cur != org_id:
        raise TenantMismatch("Changement de société interdit dans une requête épinglée")
    _org.set(org_id)
    _pinned.set(True)


def soft_set_org(org_id: str | None) -> None:
    """Utilisé par Ctx : pose la société seulement si aucune n'est épinglée."""
    if org_id and not _pinned.get():
        _org.set(org_id)


@contextmanager
def org_scope(org_id: str):
    t1, t2 = _org.set(org_id), _pinned.set(True)
    try:
        yield
    finally:
        _org.reset(t1)
        _pinned.reset(t2)


async def for_each_org(fn: Callable[[], Awaitable[Any]], *, label: str = "") -> None:
    """Exécute fn() une fois par société, chaque passe épinglée sur sa base."""
    ids = [o["id"] async for o in _c().control.orgs.find({"deleted_at": {"$in": [None]}}, {"_id": 0, "id": 1})]
    for org_id in ids:
        with org_scope(org_id):
            try:
                await fn()
            except Exception:
                logger.exception("Tâche %s en échec pour la société %s", label or getattr(fn, "__name__", "?"), org_id)


async def find_in_orgs(coll: str, flt: dict, projection: dict | None = None) -> tuple[str, dict] | tuple[None, None]:
    """Pour les webhooks sans société identifiable : cherche dans chaque base. Épingle si trouvé."""
    async for o in _c().control.orgs.find({}, {"_id": 0, "id": 1}):
        doc = await _c().tenant(o["id"])[coll].find_one(flt, projection)
        if doc:
            pin_org(o["id"])
            return o["id"], doc
    return None, None


async def org_of(coll: str, flt: dict, exclude: str | None = None) -> str | None:
    """Société dont la base contient un document correspondant (sans épingler)."""
    async for o in _c().control.orgs.find({} if not exclude else {"id": {"$ne": exclude}}, {"_id": 0, "id": 1}):
        if await _c().tenant(o["id"])[coll].find_one(flt, {"_id": 1}):
            return o["id"]
    return None


async def run_in_org_of(coll: str, flt: dict, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
    """Tâche de fond de webhook : retrouve la société concernée puis exécute fn dans sa base."""
    org_id = await org_of(coll, flt)
    if not org_id:
        logger.warning("Webhook sans société correspondante : %s %s", coll, list(flt))
        return None
    with org_scope(org_id):
        return await fn(*args, **kwargs)


# --------------------------------------------------------------------------------------
# Index des liens publics
# --------------------------------------------------------------------------------------
def _token_values(doc: Any) -> list[tuple[str, str]]:
    if not isinstance(doc, dict):
        return []
    src = {**doc, **(doc.get("$set") or {})}
    return [(f, v) for f in TOKEN_FIELDS if isinstance(v := src.get(f), str) and len(v) >= 32]


async def _index_tokens(coll: str, docs: list) -> None:
    org = _org.get()
    if not org:
        return
    for d in docs:
        for field, value in _token_values(d):
            await _c().control.link_index.update_one(
                {"_id": value}, {"$set": {"org_id": org, "coll": coll, "field": field}}, upsert=True)


def _token_in_filter(flt: Any) -> str | None:
    if isinstance(flt, dict):
        for f in TOKEN_FIELDS:
            if isinstance(v := flt.get(f), str):
                return v
    return None


async def _resolve_token(flt: Any) -> bool:
    token = _token_in_filter(flt)
    if not token:
        return False
    hit = await _c().control.link_index.find_one({"_id": token})
    if not hit:
        return False
    pin_org(hit["org_id"])
    return True


# --------------------------------------------------------------------------------------
# Base et collections routées
# --------------------------------------------------------------------------------------
_ASYNC_READS = {"find_one", "count_documents", "distinct", "find_one_and_update", "find_one_and_delete",
                "find_one_and_replace", "update_one", "update_many", "delete_one", "delete_many", "replace_one"}
_WRITES_INDEXED = {"update_one", "update_many", "find_one_and_update", "replace_one"}


class RoutedCollection:
    def __init__(self, name: str):
        self._name = name

    def _target(self):
        if self._name in PLATFORM:
            return _c().control[self._name]
        org = _org.get()
        if not org:
            raise TenantContextMissing(f"Collection « {self._name} » lue sans société active")
        return _c().tenant(org)[self._name]

    def __getattr__(self, attr: str):
        if self._name in PLATFORM or attr not in _ASYNC_READS | {"insert_one", "insert_many"}:
            return getattr(self._target(), attr)

        async def call(*a, **k):
            flt = a[0] if a else k.get("filter")
            if not _org.get() and not await _resolve_token(flt):
                if _token_in_filter(flt):  # lien public inconnu : « introuvable », pas une erreur
                    return {"find_one": None, "count_documents": 0}.get(attr)
                raise TenantContextMissing(f"{self._name}.{attr} sans société active")
            res = await getattr(self._target(), attr)(*a, **k)
            if attr in _WRITES_INDEXED and len(a) > 1:
                await _index_tokens(self._name, [a[1]])
            elif attr == "insert_one" and a:
                await _index_tokens(self._name, [a[0]])
            elif attr == "insert_many" and a:
                await _index_tokens(self._name, list(a[0]))
            return res
        return call

    def __getitem__(self, sub: str):  # db.fs.files, etc.
        return RoutedCollection(f"{self._name}.{sub}")


class RoutedDatabase:
    """Remplace AsyncIOMotorDatabase dans core.py."""

    def __getitem__(self, name: str) -> RoutedCollection:
        return RoutedCollection(name)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in DB_ATTRS:
            org = _org.get()
            return getattr(_c().tenant(org) if org else _c().control, name)
        return RoutedCollection(name)


async def assert_split_done() -> None:
    """Refuse de démarrer sur une ancienne base unique non migrée : les sociétés y
    apparaîtraient vides. Lancer d'abord scripts_saas/split_tenants.py."""
    control = _c().control
    legacy = {"events", "contacts", "quotes"} & set(await control.list_collection_names())
    if legacy and await control.events.count_documents({}, limit=1):
        raise RuntimeError(
            f"La base plateforme « {control.name} » contient des données métier ({sorted(legacy)}) : "
            "c'est une base unique non migrée. Lancez scripts_saas/split_tenants.py vers une nouvelle base, "
            "puis pointez CONTROL_DB sur la base plateforme obtenue.")


# --------------------------------------------------------------------------------------
# Création d'une base société
# --------------------------------------------------------------------------------------
async def provision(org_id: str, indexes: dict, cluster: str | None = None) -> dict:
    """Crée (ou complète) la base d'une société : emplacement dans l'annuaire puis index."""
    c = _c()
    org = await c.control.orgs.find_one({"id": org_id}, {"_id": 0, "db": 1}) or {}
    placement = org.get("db") or {"cluster": cluster or "default", "name": tenant_db_name(org_id)}
    await c.control.orgs.update_one({"id": org_id}, {"$set": {"db": placement}})
    _placements[org_id] = (placement["cluster"], placement["name"])
    tdb = c.tenant(org_id)
    for coll, models in indexes.items():
        if coll in PLATFORM:
            continue
        for model in models:
            try:
                await tdb[coll].create_indexes([model])
            except Exception as exc:  # index déjà présent avec d'autres options, etc.
                logger.warning("Index %s.%s (%s) : %s", tdb.name, coll, model.document.get("name"), exc)
    return placement
