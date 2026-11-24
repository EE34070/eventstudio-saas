# Architecture — plateforme SaaS modulaire pour les professionnels de l'événementiel

Nom de code : **EventStudio** (à remplacer par la marque définitive, à vérifier à l'INPI/EUIPO avant tout dépôt de domaine).

## 1. Décision structurante : un seul produit, Exclusivity Events en est le premier client

Ne pas maintenir deux applications (l'app d'Exclusivity Events et une copie commerciale). Le dépôt `event-cycle` devient le produit ; Exclusivity Events et Le Frenchie y sont des **organisations clientes comme les autres** (tenant n° 1). Chaque correctif profite à tous, et Exclusivity Events teste en conditions réelles tout ce qui sera vendu.

Ce dépôt est le **socle de référence** : il fixe la structure cible (core + modules), les règles d'isolation et le système d'offres, avec des tests qui passent. Le code métier déjà construit dans Emergent y est migré module par module (voir §10).

## 2. Vue d'ensemble

```
                       ┌──────────────────────────────┐
  www.produit.com ───► │ Site vitrine (Webflow)       │  tarifs, inscription, SEO
                       └──────────────────────────────┘
                       ┌──────────────────────────────┐
  app.produit.com ───► │ Frontend React (Cloudflare   │  SPA, CDN mondial, _headers CSP
                       │ Pages)                        │
                       └──────────────┬───────────────┘
                                      │ HTTPS + JWT Clerk + X-Org-Id
                       ┌──────────────▼───────────────┐      ┌───────────────────┐
  api.produit.com ───► │ API FastAPI (Render, 2 inst.)│◄────►│ Clerk (identité)  │
                       │  core/  platform/  modules/  │      └───────────────────┘
                       └───┬─────────┬─────────┬──────┘
                           │         │         │ file de tâches
                 ┌─────────▼──┐ ┌────▼─────┐ ┌─▼──────────────────────────┐
                 │ MongoDB    │ │ R2 (UE)  │ │ Worker arq + Redis (Render)│
                 │ Atlas (UE) │ │ fichiers │ │ IA, OCR, sync Gmail/WA,     │
                 └────────────┘ └──────────┘ │ relances, purge, exports    │
                                             └─┬──────────────────────────┘
                                               ▼
                     Stripe · Anthropic · Yousign · Pennylane/PDP · Gmail · WhatsApp · Meta
```

Stack conservée (celle déjà en production pour Exclusivity Events) : FastAPI + React + MongoDB Atlas + Clerk + R2, Render + Cloudflare. Aucune réécriture technologique : le code Emergent existant reste réutilisable.

> Sur MongoDB vs PostgreSQL : PostgreSQL serait le choix « manuel » pour des données financières très relationnelles. Mais avec plus de 50 lots déjà développés sur MongoDB, migrer coûterait des mois pour un gain faible à votre échelle. On garde MongoDB, avec : transactions multi-documents (replica set), validation stricte par Pydantic, index composés `org_id`, et le dépôt garde-fou ci-dessous. À réévaluer seulement si un module comptable complet entrait dans le produit (aujourd'hui délégué à Pennylane).

## 3. Arborescence

```
backend/app/
  core/            socle — ne contient aucune règle métier
    config.py        variables d'environnement
    auth.py          vérification JWT Clerk côté serveur
    tenancy.py       TenantContext + guard(module, permission)
    repository.py    TenantRepository : seule porte d'accès des modules à la base
    rbac.py          rôles et permissions
    entitlements.py  plans, add-ons, limites → modules actifs
    modules.py       registre auto-découvert des modules
    security.py      en-têtes HTTP, chiffrement des secrets, clés R2 préfixées
    storage.py       URL signées R2
  platform/        services transverses : /me, facturation Stripe, portails externes
  modules/<clé>/   un dossier par module : __init__.py (MANIFEST), router.py, service.py, models.py
  workers/         tâches asynchrones et planifiées
frontend/src/
  core/            client API, session, registre de modules, layout
  modules/<clé>/   module.tsx (routes + navigation) et pages — même clé que le backend
```

Ajouter un module = créer `backend/app/modules/<clé>/` et `frontend/src/modules/<clé>/`. Les deux sont découverts automatiquement.

## 4. Multi-tenant : une base par société

```
Cluster partagé « default » (Atlas, Paris)          Cluster dédié « dedie-xxx » (offre Entreprise)
 ├─ platform    sociétés, memberships, abonnements,   └─ t_<org_id>   données d'un grand client
 │              annuaire des bases, journal migrations
 ├─ t_<org_a>   toutes les données de la société A
 ├─ t_<org_b>   toutes les données de la société B
 └─ …
```

| Règle | Mise en œuvre |
|---|---|
| Une base par société | `t_<org_id>`, emplacement enregistré dans `orgs.db = {cluster, name}` ; plusieurs clusters possibles (`TENANT_CLUSTERS`) |
| Base plateforme séparée | `platform` : sociétés, memberships, utilisateurs, abonnements, journal des migrations — aucune donnée métier |
| Création automatique | `create_org()` choisit le cluster le moins rempli (ou le cluster dédié), crée la base, ses collections et index, la membership du propriétaire ; idempotent |
| Mises à jour de structure | Migrations versionnées appliquées à chaque base (`scripts/migrate.py`, lancé à chaque déploiement) ; version stockée dans la base société |
| Société active | Choisie via `X-Org-Id` parmi les memberships de l'utilisateur, revalidée côté serveur (403 sinon) |
| Aucun accès base direct depuis un module | `TenantRepository(ctx, collection)` ouvre la base de la société active et refuse une base qui ne correspond pas ; test statique en CI |
| Double sécurité | `org_id` conservé dans chaque document et filtre : permet aussi de déplacer une société d'un cluster à un autre |
| Fichiers | Clés R2 `org/{org_id}/…`, bucket privé, URL signées courtes |
| Tâches asynchrones | Contexte « système » limité à une société et à sa base |
| Fin de contrat | `drop_org()` supprime la base entière après le délai de restitution |
| Capacité | Atlas recommande 5 000 collections+index en M10, 10 000 en M20/M30, 100 000 en M40+ : environ 35 sociétés par cluster M10, ensuite M30/M40 ou nouveau cluster (`MAX_TENANTS_PER_CLUSTER`) |

Tests bloquants en CI : `tests/test_tenant_isolation.py` (accès croisés, en-tête falsifié, `org_id` injecté, module hors offre, rôles, impayé, prestataire multi-sociétés) et `tests/test_database_per_tenant.py` (données physiquement dans la bonne base, cluster dédié, création idempotente, migrations, suppression).

## 5. Modules et offres

### Catalogue

| Catégorie | Modules (clé) |
|---|---|
| Core (toujours actifs) | `contacts`, `events` |
| Ventes | `crm`, `quotes`, `invoicing`, `client_portal` |
| Opérations | `catalog`, `inventory`, `logistics`, `staff`, `planning`, `floorplan` |
| Métiers | `dj`, `sound_light`, `photobooth`, `wedding_planner`, `catering` |
| Gestion | `purchasing`, `finance`, `payroll` (FR), `communication`, `messaging` |

Chaque manifeste déclare ses dépendances : activer `logistics` active automatiquement `inventory` et `catalog`. Le champ `market` marque les modules liés au droit français (pôle social / CDDU, e-facturation) pour pouvoir ouvrir d'autres pays sans les proposer.

### Droits commerciaux (entitlements)

`modules actifs = core ∪ plan ∪ add-ons ∪ forçages − désactivations`, puis fermeture par dépendances. Les plans sont **dans le code** (versionnés, testés) ; Stripe ne porte que les prix. Proposition de départ, calée sur le marché (Halgaros annonce 29 / 79 / 199 € HT par mois) :

| | Essentiel | Pro | Agence | Entreprise |
|---|---|---|---|---|
| Utilisateurs inclus | 1 | 5 | 15 | sur devis |
| Ventes (CRM, devis, facturation, portail) | ✓ | ✓ | ✓ | ✓ |
| Opérations (stock, logistique, staff, déroulé, plans) | catalogue seul | ✓ | ✓ | ✓ |
| Modules métier | 1 au choix | tous | tous | tous |
| Gestion (finance, achats, social, communication) | — | achats, messagerie | ✓ | ✓ |
| Crédits IA / mois | 200 | 2 000 | 10 000 | sur devis |

Un abonnement impayé ou résilié passe l'organisation **en lecture seule** (HTTP 402 sur les écritures) : elle garde l'accès à ses données et à l'export (RGPD).

**Votre différenciation** face aux offres existantes : logistique multi-entrepôts et véhicules, configurateur de scène et nomenclatures, import IA des devis fournisseurs, réemploi du matériel déplacé, finance prévisionnelle alimentée par les prestations, pôle social intermittents. Ce sont les modules à mettre en avant à la vente.

## 6. Rôles, membres et portails externes

- Identité : Clerk (e-mail + Google, 2FA facultative, une seule étape e-mail). Rôles et appartenances : **notre base** (`memberships`), pas Clerk Organizations — on reste maître des droits et on peut changer de fournisseur d'identité.
- Rôles internes : `owner`, `admin`, `manager`, `sales`, `technician`, `accountant`, avec permissions `module:action` et ajouts/retraits par membre, plus restriction optionnelle des modules par membre.
- Rôles externes : `client`, `partner` (DJ, staff, prestataires), `organizer` (wedding planner, agence). Ils n'utilisent que `/api/portal/*`, avec des schémas de sortie dédiés : jamais de prix d'achat, marges ou notes internes.
- Un prestataire travaille pour plusieurs organisations avec **un seul compte** (une membership par organisation) : c'est un argument d'acquisition, chaque DJ invité découvre le produit.

## 7. Frontend

- `/api/me` renvoie organisation active, liste des organisations, plan, limites, modules visibles et droits d'écriture, image de marque. **Le frontend n'affiche que ce que le serveur autorise**, mais la sécurité réelle reste côté API.
- Registre de modules (`import.meta.glob`) : navigation regroupée par catégorie, routes créées uniquement pour les modules souscrits, pages chargées à la demande (le module Finance n'est jamais téléchargé par un client Essentiel).
- Changement d'organisation : vidage complet du cache React Query, aucune donnée ne survit au changement.
- Marque blanche : nom, logo, couleurs lus depuis l'organisation (et ses marques), jamais codés en dur.
- Langues : interface FR/EN dès la V1 (vos clients américains, et l'ouverture hors France), documents dans la langue du contact.

## 8. Traitements asynchrones et IA

- Worker `arq` + Redis (service séparé sur Render) : IA, OCR des factures d'achat, synchronisation Gmail/WhatsApp, relances, e-mails, exports, purge de corbeille, sauvegardes.
- IA via l'API Anthropic : le texte collé ou le PDF importé est traité comme **donnée** (pas comme instruction), la sortie est validée par schéma et reste un brouillon jusqu'à validation humaine. Chaque appel décompte des crédits IA de l'organisation (limite du plan) : c'est votre principal coût variable, il doit être mesuré et facturable.

## 9. Intégrations et paiements

| Besoin | Choix |
|---|---|
| Abonnements SaaS | **Stripe Billing** + Stripe Tax (TVA UE), portail client Stripe ; webhook idempotent → `orgs.subscription` |
| Paiements des clients de vos clients (acomptes, soldes) | **Stripe Connect** (comptes Express) : chaque organisation encaisse sur son compte, vous pouvez prélever une commission (modèle Halgaros) |
| Signature électronique | Yousign (API, clé par organisation) |
| Comptabilité / e-facturation | Connecteurs export (Pennylane d'abord) et transmission via une **plateforme agréée partenaire** par API, plutôt que de devenir soi-même plateforme agréée |
| Messagerie | Gmail (OAuth par organisation), WhatsApp Business (API Meta), Instagram/Facebook |
| Secrets d'intégration | Par organisation, chiffrés (Fernet, clé `ENCRYPTION_KEY`), jamais renvoyés au frontend |

## 10. Migration depuis l'application Exclusivity Events

1. **Laisser finir** les lots en cours dans Emergent, dont le lot « multi-organisation et paramètres société » (déjà en file) : il pose `org_id`, les memberships et la suppression du codé en dur.
2. **Restructurer `event-cycle`** selon l'arborescence ci-dessus : `core/` repris de ce socle, chaque fonctionnalité rangée dans `modules/<clé>/` avec son manifeste, toutes les routes passées sous `guard()` et `TenantRepository`.
3. **Activer les offres** : `entitlements.py`, `/api/me`, registre frontend. Exclusivity Events en plan « Entreprise ».
4. **Tests d'isolation** en CI, puis organisation pilote externe (un DJ ou loueur ami) pendant 1 à 2 mois.
5. **Bascule en UE** (voir HEBERGEMENT.md) avant le premier client payant.
6. **Commercialisation** : inscription en libre-service, essai 14 jours, Stripe, site vitrine.

Hors périmètre de la V1 commerciale : sous-domaines par client, SSO entreprise, application mobile native (une PWA suffit pour les feuilles de mission).
