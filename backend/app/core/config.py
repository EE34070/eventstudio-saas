"""Configuration centralisée (12-factor) : tout vient des variables d'environnement."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: Literal["development", "staging", "production"] = "development"
    APP_NAME: str = "EventStudio"  # nom produit (marque blanche : surchargé par org)

    # Base de données
    MONGO_URI: str = "mongodb://localhost:27017"  # cluster partagé « default »
    CONTROL_DB: str = "platform"                  # base plateforme (sociétés, accès, abonnements)
    # Clusters supplémentaires pour bases sociétés dédiées, JSON : {"dedie-acme": "mongodb+srv://..."}
    TENANT_CLUSTERS: str = "{}"
    # Nombre max de sociétés par cluster partagé avant d'en ouvrir un autre
    # (Atlas recommande 5 000 collections+index en M10, 10 000 en M20/M30, 100 000 en M40+)
    MAX_TENANTS_PER_CLUSTER: int = 35

    # Redis (file de tâches, rate limiting, cache)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Authentification (Clerk)
    CLERK_ISSUER: str = ""  # ex. https://clerk.monproduit.com
    CLERK_JWKS_URL: str = ""  # ex. https://clerk.monproduit.com/.well-known/jwks.json
    CLERK_AUTHORIZED_PARTIES: list[str] = []  # ex. ["https://app.monproduit.com"]

    # Sécurité
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    ENCRYPTION_KEY: str = ""  # clé Fernet pour chiffrer les secrets d'intégration par organisation

    # Stockage fichiers (Cloudflare R2, API S3)
    R2_ENDPOINT: str = ""  # https://<account>.eu.r2.cloudflarestorage.com (juridiction UE)
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = "eventstudio-files"

    # Facturation SaaS
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # IA
    ANTHROPIC_API_KEY: str = ""

    # Observabilité
    SENTRY_DSN: str = ""

    @property
    def is_prod(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
