"""Accès MongoDB : une base « plateforme » + une base par société cliente.

    base plateforme (CONTROL_DB)     sociétés, memberships, utilisateurs, abonnements,
                                     annuaire « où est la base de chaque société »
    base société  t_<org_id>         toutes les données métier de CETTE société

Les bases sociétés peuvent vivre sur plusieurs clusters (TENANT_CLUSTERS) :
le cluster partagé « default », et des clusters dédiés pour l'offre Entreprise.
L'emplacement est enregistré dans orgs.db = {"cluster": ..., "name": ...}.

Règle : aucun module métier n'ouvre une base lui-même. Il passe par
TenantRepository (core/repository.py), qui utilise la base de la société active.
"""
import json
import re

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import get_settings

# Collections de la base plateforme. Elles n'existent JAMAIS dans une base société.
PLATFORM_COLLECTIONS = {"orgs", "memberships", "users", "plans", "billing_events", "migrations_log", "invitations"}

_ORG_ID = re.compile(r"^[a-z0-9_]{3,40}$")


def tenant_db_name(org_id: str) -> str:
    if not _ORG_ID.match(org_id):
        raise ValueError("Identifiant de société invalide")
    return f"t_{org_id}"


class ClusterRouter:
    """Garde un client Mongo par cluster et retrouve la base d'une société."""

    def __init__(self, clients: dict[str, AsyncIOMotorClient], control_cluster: str = "default"):
        if control_cluster not in clients:
            raise RuntimeError("Cluster de la base plateforme introuvable")
        self.clients = clients
        self.control_cluster = control_cluster

    @classmethod
    def from_settings(cls) -> "ClusterRouter":
        s = get_settings()
        uris: dict[str, str] = {"default": s.MONGO_URI, **json.loads(s.TENANT_CLUSTERS or "{}")}
        clients = {
            name: AsyncIOMotorClient(uri, tz_aware=True, uuidRepresentation="standard")
            for name, uri in uris.items()
        }
        return cls(clients)

    @property
    def control(self) -> AsyncIOMotorDatabase:
        return self.clients[self.control_cluster][get_settings().CONTROL_DB]

    def tenant(self, org: dict) -> AsyncIOMotorDatabase:
        placement = org.get("db") or {}
        cluster = placement.get("cluster", "default")
        if cluster not in self.clients:
            raise RuntimeError(f"Cluster « {cluster} » non configuré pour la société {org['_id']}")
        name = placement.get("name") or tenant_db_name(org["_id"])
        if name == get_settings().CONTROL_DB:
            raise RuntimeError("Une société ne peut pas utiliser la base plateforme")
        return self.clients[cluster][name]


def get_router(request: Request) -> ClusterRouter:
    return request.app.state.router


def get_control_db(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.router.control


async def ensure_control_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.memberships.create_index([("user_id", 1), ("org_id", 1)], unique=True)
    await db.memberships.create_index([("org_id", 1), ("role", 1)])
    await db.orgs.create_index("slug", unique=True)
