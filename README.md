# EventStudio — SaaS de gestion pour les professionnels de l'événementiel

Produit commercialisable issu de l'application Exclusivity Events : une base de données par
société, des offres (Essentiel, Pro, Agence, Entreprise) et la migration des données existantes.
Voir **docs/SAAS.md** (fonctionnement SaaS), docs/HEBERGEMENT.md (hébergement UE),
docs/ARCHITECTURE.md, docs/SECURITE.md, docs/DEPLOIEMENT.md.

---

# Exclusivity Events — ERP événementiel

Application web de gestion de prestations événementielles, en français, multi-sociétés.
Elle suit un événement de bout en bout : demande → devis → confirmation → préparation → chargement → livraison → jour J → retour matériel → facturation → clôture.

## Modules

| Module | Contenu |
| --- | --- |
| Tableau de bord | Indicateurs, prochains événements, alertes (conflits de matériel, manquants au chargement) |
| Événements | Liste et kanban, fiche à onglets (infos, prestations, matériel, équipe, finances, documents), chevauchements de dates |
| Planning | Calendrier, déplacement d'un événement par glisser-déposer |
| Catalogue & matériel | Stock, packs, maintenance, disponibilité sur une période, fiches produits (photo + description) |
| Chargement du jour | Check-list par véhicule, signalement des manquants, véhicules |
| Livraison du jour | Tournée, photos à l'arrivée, signature du client, bon de livraison PDF |
| Devis & factures | Devis depuis l'événement, TVA par ligne, acompte, PDF, devis en ligne, facture d'acompte et de solde, paiements |
| Envoi et signature | Envoi du devis par e-mail ; signature électronique Yousign (inactive tant que la clé n'est pas fournie) |
| Relances impayés | Factures en retard, message prêt à envoyer, relances automatiques J+7 / J+15 / J+30 |
| Contacts | Clients et prospects, historique des échanges |
| Lieux | Fiches, carte OpenStreetMap, plans et photos, espaces par lieu, plan d'implantation |
| Équipe | Membres, compétences, missions |
| Organisation | Coordonnées, mentions, conditions générales, modules métier actifs |

Pages présentes dans le menu mais non développées : Prestataires, Notes de frais, Compta, Commercial, Documents, Écrans TV.

## Stack

- Frontend : React 19 (Create React App + CRACO), Tailwind CSS, composants shadcn/ui, Leaflet, Recharts
- Backend : FastAPI, Motor (MongoDB), ReportLab (PDF), Pillow
- Base de données : MongoDB
- Authentification : Clerk (Google et e-mail/mot de passe)
- Services externes : stockage de fichiers et e-mail gérés par Emergent, Yousign (signature)

## Structure des dossiers

```
backend/
  server.py            application FastAPI, index, démarrage
  core.py              base de données, rôles, permissions, contexte de requête
  clerk_auth.py        vérification des sessions Clerk
  routes_main.py       société, utilisateurs, équipe, contacts, lieux
  routes_ops.py        matériel, packs, événements, tableau de bord, recherche
  routes_billing.py    devis, factures, paiements, PDF, véhicules, chargement
  routes_comms.py      envoi de devis, signature Yousign, relances
  routes_delivery.py   livraison, bon signé, plan d'implantation
  routes_files.py      téléversement de fichiers, devis public
  emailer.py           envoi d'e-mails
  seed.py              données de démonstration
  tests/               tests pytest
frontend/src/
  pages/               une page par écran
  components/          layout, events, billing, catalogue, ui (shadcn)
  lib/                 client API, constantes, fichiers
  context/             utilisateur et société courants
scripts/               utilitaires de test (jetons Clerk)
docs/ARCHITECTURE.md   modèle de données, routes, rôles
.emergent/crons.yml    tâches planifiées (chargement 6 h, relances 9 h, heure de Paris)
```

## Lancement en local

Prérequis : Python 3.11, Node 20 + Yarn 1.22, MongoDB.

Backend :

```
cd backend
cp .env.example .env          # puis renseigner les valeurs
pip install -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

Frontend :

```
cd frontend
cp .env.example .env          # puis renseigner les valeurs
yarn install
yarn start
```

L'application s'ouvre sur http://localhost:3000 ; toutes les routes de l'API sont préfixées par `/api`.

## Variables d'environnement

Backend (`backend/.env`) :

| Variable | Rôle | Obligatoire |
| --- | --- | --- |
| MONGO_URL | Connexion MongoDB | oui |
| DB_NAME | Nom de la base | oui |
| CORS_ORIGINS | Origines autorisées | non |
| CLERK_PUBLISHABLE_KEY | Clé publique Clerk | oui |
| CLERK_SECRET_KEY | Clé secrète Clerk | oui |
| ADMIN_EMAIL | E-mail(s) du propriétaire | non |
| WEBHOOK_CRON_SECRET | Protège `/api/cron/*` | oui |
| EMERGENT_LLM_KEY | Stockage des fichiers | oui |
| EMERGENT_EMAIL_KEY | Envoi d'e-mails | oui |
| EMAIL_FROM_NAME | Nom d'expéditeur | oui |
| YOUSIGN_BASE_URL | URL de l'API Yousign | pour la signature |
| YOUSIGN_API_KEY | Clé API Yousign | pour la signature |
| YOUSIGN_WEBHOOK_SECRET | Secret du webhook Yousign | pour la signature |
| INTEGRATION_PROXY_URL | Proxy d'intégrations | non |

Frontend (`frontend/.env`) :

| Variable | Rôle |
| --- | --- |
| REACT_APP_BACKEND_URL | URL publique du backend |
| WDS_SOCKET_PORT | Port du rechargement à chaud |
| ENABLE_HEALTH_CHECK | Contrôle de santé du serveur de développement |

Aucun secret n'est écrit dans le code ; les fichiers `.env` ne sont pas versionnés.

## Tests

Les tests appellent le backend en fonctionnement et créent des sessions Clerk de test : le backend doit être démarré et les clés Clerk renseignées.

```
cd backend
pytest tests/ -n 0
```
