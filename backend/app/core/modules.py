"""Registre des modules.

Chaque module vit dans app/modules/<clé>/ et expose un MANIFEST dans son __init__.py.
Le manifeste décrit : catégorie, dépendances, permissions, router (optionnel),
index MongoDB et collections dont il est propriétaire. Le registre est découvert
automatiquement au démarrage ; ajouter un module = ajouter un dossier.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass
class ModuleManifest:
    key: str
    name: str
    category: str  # core | ventes | operations | metiers | gestion | integrations
    description: str = ""
    is_core: bool = False           # toujours actif, quel que soit le plan
    depends_on: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)  # ex. ["read", "write", "send"]
    collections: list[str] = field(default_factory=list)  # collections métier (org_id obligatoire)
    indexes: dict[str, list[list[tuple[str, int]]]] = field(default_factory=dict)
    router: "APIRouter | None" = None
    status: str = "planned"         # planned | beta | stable
    market: str | None = None       # ex. "FR" pour un module dépendant du droit français


_REGISTRY: dict[str, ModuleManifest] = {}


def discover() -> dict[str, ModuleManifest]:
    if _REGISTRY:
        return _REGISTRY
    import app.modules as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"app.modules.{info.name}")
        manifest: ModuleManifest = getattr(mod, "MANIFEST")
        if manifest.key in _REGISTRY:
            raise RuntimeError(f"Module en double : {manifest.key}")
        _REGISTRY[manifest.key] = manifest

    # Vérifie que toutes les dépendances existent
    for m in _REGISTRY.values():
        missing = [d for d in m.depends_on if d not in _REGISTRY]
        if missing:
            raise RuntimeError(f"{m.key} dépend de modules inconnus : {missing}")
    return _REGISTRY


def registry() -> dict[str, ModuleManifest]:
    return discover()


def dependency_closure(keys: set[str]) -> set[str]:
    reg = registry()
    out, stack = set(), list(keys)
    while stack:
        k = stack.pop()
        if k in out or k not in reg:
            continue
        out.add(k)
        stack.extend(reg[k].depends_on)
    return out
