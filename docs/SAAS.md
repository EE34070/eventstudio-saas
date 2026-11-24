# Le SaaS : une base par société, offres, migration

Ce dépôt est le produit commercialisable. Son code vient de l'application Exclusivity Events
(`event-cycle`), avec trois ajouts : une base de données par société, des offres commerciales
et un script de migration. Exclusivity Events y devient une société cliente comme les autres.

## 1. Une base par société

```
Cluster partagé « default »                     Cluster dédié (offre Entreprise)
 ├─ platform   orgs, users, module_defs,          └─ t_<org_id>
 │             link_index, job_locks, cron_runs,
 │             webhook_events, oauth_states
 ├─ t_<org A>  événements, devis, stock… de A
 └─ t_<org B>  … de B
```

`backend/tenant_router.py` remplace la base unique sans réécrire les 57 fichiers de routes :
l'objet global `db` de `core.py` envoie chaque collection soit vers la base plateforme, soit vers
la base de la **société active**.

| Situation | Comment la société active est connue |
|---|---|
| Requête d'un membre ou d'un portail | `core.current_member` épingle la société du compte pour toute la requête ; un changement en cours de requête est refusé (`TenantMismatch`) |
| Lien public (devis, mission, DJ, musique, iCal…) | l'empreinte du jeton (`share_hash`, `token_hash`, `guest_token_hash`, `ical_hash`) est indexée dans `platform.link_index` à l'écriture ; la lecture publique retrouve la société |
| Tâches planifiées et crons | `tenant_router.for_each_org` : une passe par société, épinglée sur sa base (chaque société traitée une seule fois) |
| Webhooks Gmail et Yousign, retour OAuth Google | société retrouvée (`org_of`, `oauth_states.org_id`) puis épinglée |
| Téléchargement signé `/portal/dl/{org_id}/…` | société de l'URL, après vérification de la signature |
| Inscription (`/api/onboarding`) | création de la base `t_<org_id>` et de ses index (`tenant_router.provision`) |

**Sécurité par défaut :** une requête sur une collection métier sans société active lève
`TenantContextMissing` (erreur 500 journalisée) au lieu de lire au mauvais endroit. Un lien public
inconnu répond « introuvable ».

**Démarrage protégé :** le serveur refuse de démarrer si la base plateforme contient encore des
données métier (ancienne base unique non migrée), pour éviter d'afficher des sociétés vides.

Variables : `MONGO_URL` (cluster partagé), `CONTROL_DB=platform`, `TENANT_CLUSTERS` (JSON des
clusters dédiés). Capacité indicative : environ 35 sociétés par cluster M10 (limite recommandée
par Atlas de 5 000 collections et index), davantage en M30/M40.

## 2. Offres (`backend/plans.py`)

| | Essentiel | Pro | Agence | Entreprise |
|---|---|---|---|---|
| Rubriques | ventes : événements, contacts, CRM, devis, facturation, catalogue, lieux, prestataires, messagerie, saisie IA, to-do, équipe, portails, paramètres | + stock, logistique, véhicules, staff, musique DJ, achats, notes de frais | + finance, pôle social, communication | tout |
| Modules métier (DJ, son & lumière…) | 1 | tous | tous | tous |
| Utilisateurs | 1 | 5 | 15 | illimité |

- Contrôle à chaque requête interne (`core._enforce_plan`) : rubrique hors offre → 403, abonnement
  impayé ou essai expiré → **lecture seule** (402 sur les écritures, export toujours possible).
- `orgs.subscription = {plan, status, trial_ends_at, addons, extra_seats}` ; une société sans
  abonnement (clients historiques, dont Exclusivity Events) est en offre Entreprise.
- Inscription en libre-service : essai Pro de 14 jours.
- `/api/me` renvoie `plan` ; le menu masque les rubriques hors offre et un bandeau signale l'essai
  ou la lecture seule.
- À brancher : Stripe Billing (webhook → `orgs.subscription`), page de tarifs.

## 3. Migration des données d'Exclusivity Events

`backend/scripts_saas/split_tenants.py` copie la base unique actuelle vers la nouvelle
organisation (idéalement un nouveau cluster Atlas en UE). La source n'est jamais modifiée.

```bash
cd backend
SRC_MONGO_URL="<cluster actuel>" SRC_DB=exclusivity \
MONGO_URL="<nouveau cluster UE>" CONTROL_DB=platform \
python -m scripts_saas.split_tenants --dry-run    # simulation : comptes par collection et par société
# … puis --apply : copie, index des liens publics, index des bases, vérification des comptes
```

Les documents sans société identifiable sont listés et non copiés. Faire un instantané Atlas avant,
et basculer les variables Render seulement après une vérification sans écart.

## 4. Tests

```bash
cd backend && pip install mongomock-motor pytest-asyncio && python -m pytest tests_saas -q
```

Sans serveur, sans Clerk ni MongoDB réels. Ils couvrent : données physiquement dans la base de
leur société, invisibilité entre sociétés, cluster dédié, refus sans société active, liens publics,
**toutes les routes GET authentifiées et toutes les routes publiques** (aucune erreur de routage),
chaque tâche planifiée et chaque cron, offres et lecture seule, inscription, migration.
Les tests historiques `backend/tests/` (bout en bout avec un vrai serveur et Clerk) restent valables.

## 5. Indépendance vis-à-vis d'Emergent

Le SaaS ne dépend plus d'aucun service Emergent :
- e-mails : `EMAIL_PROVIDER=resend` (défaut) ou `smtp` ;
- fichiers : `STORAGE_PROVIDER=s3` (défaut, Cloudflare R2 ou tout stockage S3) ou `local` en développement ;
- IA : appel direct à l'API Anthropic (`LLM_API_KEY`) ;
- dépendances : uniquement PyPI (plus de dépôt Emergent, plus de `emergentintegrations`).

Migration : `--default-org-slug exclusivity-events` (ou `SPLIT_DEFAULT_ORG_SLUG`) rattache à cette
société les documents historiques sans `org_id` (ex. `import_catalogue_odoo`).

## 6. Reste à faire

- Scripts d'exploitation historiques (`scripts/purge_*.py`, `migrate_org.py`, `backup_mongo.py`) :
  écrits pour une base unique, à adapter (boucle `for_each_org`).
- Textes encore propres à Exclusivity Events dans quelques routes et dans `seed.py` (lot
  « paramètres société » : nom, CGV, e-mails lus depuis la société).
- Stripe Billing, page de tarifs, nom définitif du produit et domaine.
