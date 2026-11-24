# EventStudio — socle SaaS modulaire pour l'événementiel

Socle de référence (backend + frontend) de la version commercialisable de l'application Exclusivity Events Studio.

- `docs/ARCHITECTURE.md` — décisions, multi-tenant, modules et offres, migration depuis l'app actuelle
- `docs/HEBERGEMENT.md` — hébergement UE, environnements, budget, sauvegardes

## Démarrage local

```bash
docker compose up -d                       # MongoDB (replica set) + Redis
cd backend && cp .env.example .env
pip install -r requirements-dev.txt
pytest -q                                   # 17 tests, dont l'isolation multi-tenant
uvicorn app.main:app --reload               # http://localhost:8000/docs
arq app.workers.worker.WorkerSettings       # worker (autre terminal)

cd ../frontend && cp .env.example .env.local
npm install && npm run dev                  # http://localhost:5173
```

## Ajouter un module

1. `backend/app/modules/<clé>/__init__.py` : `MANIFEST = ModuleManifest(...)` (dépendances, collections, index commençant par `org_id`, router)
2. Routes : `Depends(guard("<clé>", "read" | "write"))` et `TenantRepository` — jamais d'accès direct à la base
3. `frontend/src/modules/<clé>/module.tsx` : routes et navigation, même clé
4. L'ajouter à un plan dans `core/entitlements.py`, puis un test d'isolation

## Déploiement

- API + worker + Redis : `render.yaml` (Blueprint Render, région Francfort)
- Frontend : Cloudflare Pages, dossier `frontend`, commande `npm run build`, sortie `dist`
- CI : `.github/workflows/ci.yml` (tests, lint, audit des dépendances)
