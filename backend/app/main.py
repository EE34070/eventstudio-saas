"""Point d'entrée API. Monte automatiquement le router de chaque module découvert."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import ClusterRouter, ensure_control_indexes
from app.core.modules import registry
from app.core.security import SecurityHeadersMiddleware
from app.platform import billing, portal, session


def create_app(router: ClusterRouter | None = None) -> FastAPI:
    """router injectable pour les tests ; en production il est construit depuis l'environnement.

    Les index des bases sociétés ne sont PAS créés au démarrage : ils le sont à la création
    de chaque société, puis par les migrations (scripts/migrate.py), lancées au déploiement.
    """
    s = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if router is None:
            app.state.router = ClusterRouter.from_settings()
        await ensure_control_indexes(app.state.router.control)
        yield

    app = FastAPI(
        title=s.APP_NAME,
        lifespan=lifespan,
        docs_url=None if s.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if s.is_prod else "/openapi.json",
    )
    if router is not None:
        app.state.router = router

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Org-Id"],
    )

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    app.include_router(session.router, prefix="/api")
    app.include_router(billing.router, prefix="/api")
    app.include_router(portal.router, prefix="/api")
    for m in registry().values():
        if m.router is not None:
            app.include_router(m.router, prefix="/api")
    return app


app = create_app()
