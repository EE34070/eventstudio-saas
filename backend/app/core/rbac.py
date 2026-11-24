"""Rôles et permissions.

Permission = "<module>:<action>" (ex. "quotes:write", "finance:read").
Joker : "<module>:*" ou "*".
Les rôles internes servent l'équipe de l'organisation ; les rôles externes servent
les espaces clients et prestataires (DJ, staff, wedding planners invités).
"""
from enum import StrEnum


class Role(StrEnum):
    # Internes
    OWNER = "owner"            # gérant, propriétaire de l'abonnement
    ADMIN = "admin"
    MANAGER = "manager"        # chef de projet / responsable commercial
    SALES = "sales"
    TECHNICIAN = "technician"  # logistique, montage, régie
    ACCOUNTANT = "accountant"  # lecture finance, exports comptables
    # Externes (portails)
    CLIENT = "client"
    PARTNER = "partner"        # prestataire / DJ / staff engagé
    ORGANIZER = "organizer"    # wedding planner ou agence invitée sur un événement


INTERNAL_ROLES = {Role.OWNER, Role.ADMIN, Role.MANAGER, Role.SALES, Role.TECHNICIAN, Role.ACCOUNTANT}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.OWNER: {"*"},
    Role.ADMIN: {"*"},
    Role.MANAGER: {
        "crm:*", "events:*", "quotes:*", "invoicing:*", "catalog:*", "inventory:*",
        "logistics:*", "staff:*", "planning:*", "dj:*", "messaging:*", "communication:*",
        "purchasing:read", "finance:read",
    },
    Role.SALES: {"crm:*", "events:*", "quotes:*", "catalog:read", "messaging:*", "dj:read"},
    Role.TECHNICIAN: {"events:read", "inventory:*", "logistics:*", "planning:read", "catalog:read"},
    Role.ACCOUNTANT: {"invoicing:read", "finance:read", "purchasing:read", "payroll:read", "exports:*"},
    # Les portails n'utilisent jamais les routes internes : ils ont leurs routes /api/portal/*
    Role.CLIENT: {"portal:client"},
    Role.PARTNER: {"portal:partner"},
    Role.ORGANIZER: {"portal:organizer"},
}


def has_permission(granted: set[str], required: str) -> bool:
    if "*" in granted or required in granted:
        return True
    module, _, _action = required.partition(":")
    return f"{module}:*" in granted


def permissions_for(role: str, extra: list[str] | None = None, revoked: list[str] | None = None) -> set[str]:
    perms = set(ROLE_PERMISSIONS.get(Role(role), set()))
    perms |= set(extra or [])
    perms -= set(revoked or [])
    return perms
