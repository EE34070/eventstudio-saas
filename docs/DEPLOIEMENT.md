# Déploiement hors Emergent

Cible : frontend sur Cloudflare Pages, backend sur Render (Virginie), base MongoDB Atlas (AWS us-east-1, Virginie), fichiers sur Cloudflare R2.

## 1. MongoDB Atlas

1. Le cluster **Flex** existe déjà en AWS **us-east-1 (Virginie)** ; le backend Render est placé dans la même région (`region: virginia`).
2. Database Access : créer un utilisateur (mot de passe généré), rôle « Read and write to any database ».
3. Network Access : ajouter `0.0.0.0/0` (Render n'a pas d'adresse IP fixe sur l'offre Starter).
4. Connect > Drivers : copier l'URI `mongodb+srv://utilisateur:motdepasse@cluster.xxxxx.mongodb.net/`. C'est la valeur de `MONGO_URL`.

## 2. Cloudflare R2

1. Le bucket `exclusivity-app-files` existe déjà et reste **privé** : le backend vérifie les droits, puis fournit un lien de téléchargement signé valable 5 minutes.
2. R2 > Manage API Tokens : créer un jeton « Object Read & Write » limité à ce bucket. Noter l'Access Key ID, le Secret Access Key et l'endpoint `https://<identifiant-compte>.r2.cloudflarestorage.com`.

## 3. Render (backend)

1. New > Blueprint, choisir le dépôt GitHub : Render lit `render.yaml`.
2. Renseigner les variables demandées (liste en fin de document).
3. Après le premier déploiement, vérifier `https://<service>.onrender.com/api/health` → `{"status":"ok"}`.
4. Settings > Custom Domains : ajouter `api.exclusivity-events.com`, puis créer chez votre registraire le CNAME indiqué par Render.

Les index MongoDB sont créés automatiquement au démarrage. Au premier démarrage sur une base vide, la société de démonstration est créée ; importer les données (étape 6) avant le premier démarrage pour l'éviter.

## 4. Cloudflare Pages (frontend)

1. Workers & Pages > Create > Pages > Connect to Git, choisir le dépôt.
2. Root directory : `frontend` · Build command : `yarn build` · Build output directory : `build`.
3. Variables d'environnement (Production et Preview) : `REACT_APP_BACKEND_URL=https://api.exclusivity-events.com` (sans `/api`). La version de Node est lue dans `frontend/.node-version`.
4. Custom domains : ajouter `app.exclusivity-events.com`.

Le fichier `frontend/public/_redirects` assure le routage côté client (rechargement d'une page profonde).

## 5. Clerk (basculer vers votre propre compte)

L'instance Clerk utilisée dans Emergent appartient à Emergent : ses clés ne sont pas réutilisables ailleurs. Le code n'exige rien de propre à Emergent (API Clerk standard).

1. Sur clerk.com, créer un compte puis une application ; activer « Email » et « Google ».
2. Passer l'application en **production** avec le domaine `exclusivity-events.com` et créer les enregistrements DNS demandés (dont `clerk.exclusivity-events.com`). Pour Google en production, renseigner vos propres identifiants OAuth Google.
3. Vérifier que `https://app.exclusivity-events.com` figure dans les domaines / origines autorisés.
4. Sur Render : `CLERK_PUBLISHABLE_KEY` (`pk_live_…`), `CLERK_SECRET_KEY` (`sk_live_…`) et `CLERK_USE_PROXY=false`. Ce dernier réglage est obligatoire : le relais intégré ne fonctionne que si frontend et backend partagent le même domaine.
5. Premier compte admin : mettre votre e-mail dans `ADMIN_EMAIL`, puis créer votre compte sur `https://app.exclusivity-events.com/sign-up` avec cet e-mail. Vous êtes rattaché comme admin à la société dont l'identifiant est `exclusivity-events`.
6. Utilisateurs existants : les comptes Clerk ne se transfèrent pas. L'import de l'étape 6 ignore la collection `users` et détache les fiches Équipe (`--skip users --reset-clerk-links`). Chaque personne recrée son compte avec l'e-mail de sa fiche Équipe et retrouve automatiquement sa société et son rôle. Une personne sans fiche Équipe, ou dont l'e-mail diffère, arrive sur l'écran de création de société : corriger d'abord l'e-mail de sa fiche.

## 6. Migration des données

Depuis l'environnement Emergent, dans `backend/` :

```
python scripts/export_db.py --mongo-url "$MONGO_URL" --db "$DB_NAME" --out dump
python scripts/import_db.py --mongo-url "mongodb+srv://..." --db exclusivity --in dump --skip users --reset-clerk-links
```

L'import n'écrit que dans des collections vides et ne supprime rien.

Fichiers téléversés (photos, plans, bons signés), toujours depuis Emergent, avec les variables `S3_*` dans l'environnement :

```
python scripts/copy_files_to_s3.py --mongo-url "$MONGO_URL" --db "$DB_NAME"
```

Les clés de fichiers sont conservées : aucune modification de la base n'est nécessaire.

## 7. Tâches planifiées

Dans Emergent, `.emergent/crons.yml` appelle chaque jour `POST /api/cron/loading` (6 h) et `POST /api/cron/reminders` (9 h), avec `WEBHOOK_CRON_SECRET` en en-tête Bearer.

Hors Emergent, `.github/workflows/cron.yml` fait les mêmes appels. Ajouter dans GitHub > Settings > Secrets : `API_URL` (`https://api.exclusivity-events.com`) et `WEBHOOK_CRON_SECRET` (même valeur que sur Render). GitHub planifie en UTC : les heures se décalent d'une heure entre été et hiver, et l'exécution peut avoir quelques minutes de retard. Un Cron Job Render avec la même commande `curl` est une alternative payante. Seules ces deux tâches quotidiennes passent par GitHub Actions ; celles de la messagerie tournent dans le backend (section 8 bis).

## 8. Yousign

Dans Yousign, déclarer le webhook `https://api.exclusivity-events.com/api/webhooks/yousign` et reporter son secret dans `YOUSIGN_WEBHOOK_SECRET`. Pour la production, `YOUSIGN_BASE_URL=https://api.yousign.app/v3`.

## 8 bis. Messagerie Gmail

1. Google Cloud > APIs & Services : activer **Gmail API** et **Cloud Pub/Sub API**. Écran de consentement : type « Interne » si la boîte est dans votre Google Workspace (sinon « Externe », en production, ce qui impose la validation Google du droit `gmail.modify`).
2. Client OAuth « Application Web » : URI de redirection `https://api.exclusivity-events.com/api/auth/google/callback` (l'URI exacte est affichée dans Messagerie > Réglages). Reporter `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` sur Render. Le secret sert aussi à chiffrer le jeton Gmail en base : s'il change, reconnecter la boîte.
3. Pub/Sub : créer un sujet (valeur de `GMAIL_PUBSUB_TOPIC`, forme `projects/<projet>/topics/<sujet>`) et donner à `gmail-api-push@system.gserviceaccount.com` le rôle « Éditeur Pub/Sub » sur ce sujet.
4. Abonnement **push** vers `https://api.exclusivity-events.com/api/webhooks/gmail`, avec authentification activée et un compte de service dédié (son e-mail = `PUBSUB_PUSH_SA_EMAIL`). Si une audience est renseignée dans l'abonnement, la reporter dans `PUBSUB_AUDIENCE`.
5. Dans l'application : Messagerie > Réglages > Connecter Gmail (admin ou gérant). Les 90 derniers jours sont importés.
6. Tâches internes (APScheduler, dans le backend, sans GitHub Actions) : rattrapage toutes les 5 minutes, renouvellement de la surveillance Gmail chaque nuit à 2 h 30, corbeille à 3 h (heure de Paris). Un verrou MongoDB (`job_locks`) évite les doublons si plusieurs instances tournent. **Le service Render doit rester allumé en permanence : offre payante (Starter ou plus).** Sur l'offre gratuite, le serveur s'endort après 15 minutes sans trafic et ces tâches ne partent plus. Sans Pub/Sub, la messagerie fonctionne avec le seul rattrapage.
6 ter. Module Prestataires : une quatrième tâche interne tourne toutes les 15 minutes (relance à mi-délai, envoi en cascade, feuille de route J-3). Elle dépend aussi d'un serveur allumé en permanence. Les demandes partent de la boîte Gmail connectée ; aucune variable d'environnement supplémentaire.
6 bis. Quota : l'import respecte `GMAIL_QUOTA_PER_MINUTE` (3 000 unités/min par défaut, la limite Google du projet étant de 6 000), 5 lectures simultanées au plus, et reprend seul après un dépassement. Avec plusieurs instances, diviser cette valeur par le nombre d'instances.
7. IA : `ANTHROPIC_API_KEY` (SDK officiel Anthropic). Sans clé, le classement et les suggestions sont masqués.

Corbeille : une conversation supprimée, liée à un contact supprimé ou plus ancienne que la durée de conservation part en corbeille et reste restaurable 30 jours. Passé ce délai, elle est effacée définitivement de l'application chaque nuit (journal dans les logs et la collection `job_logs`). Les e-mails ne sont jamais supprimés dans Gmail.

## 8 ter. Purge des données de démonstration

Le chargement automatique de la démo est désactivé (seules les tables de configuration sont initialisées au démarrage). Pour vider une base :

1. `MONGO_URL=... DB_NAME=... python3 scripts/purge_demo.py --list-orgs` pour repérer l'identifiant de la société.
2. `python3 scripts/purge_demo.py --org <id> --keep-contact <id du contact à garder> --dry-run` : tableau « à supprimer / conservé », sans rien effacer.
3. Même commande avec `--apply` : sauvegarde JSON dans `backups/` (non versionné), puis suppression. Ajouter les variables `S3_*` pour effacer aussi les fichiers du stockage R2.
4. `--test-orgs --dry-run` puis `--apply` supprime les sociétés dont le nom commence par `TEST_` (tests automatiques).

Conservé : société et paramètres, utilisateurs, membres d'équipe liés à un compte, connexion Gmail, conversations et messages, métiers, modèles de message, modules. Les compteurs d'événements, de devis et de factures repartent à 1. Le script s'arrête si une facture a déjà été envoyée.

## 9. Variables d'environnement

Render (backend) :

| Variable | Valeur |
| --- | --- |
| MONGO_URL | URI Atlas |
| DB_NAME | `exclusivity` |
| CORS_ORIGINS | `https://app.exclusivity-events.com` |
| CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY | clés `pk_live_` / `sk_live_` de votre compte Clerk |
| CLERK_USE_PROXY | `false` |
| ADMIN_EMAIL | e-mail du propriétaire |
| WEBHOOK_CRON_SECRET | longue chaîne aléatoire |
| STORAGE_PROVIDER | `s3` |
| S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY | accès R2 |
| S3_BUCKET | `exclusivity-app-files` |
| S3_PUBLIC_BASE_URL | optionnel, seulement si le bucket devient public |
| EMAIL_PROVIDER | `resend` ou `smtp` |
| RESEND_API_KEY | si `resend` |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD | si `smtp` |
| EMAIL_FROM | adresse d'expédition sur un domaine vérifié |
| EMAIL_FROM_NAME | `Exclusivity Events` |
| YOUSIGN_BASE_URL, YOUSIGN_API_KEY, YOUSIGN_WEBHOOK_SECRET | signature (optionnel) |
| GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET | client OAuth Google (messagerie) |
| GOOGLE_REDIRECT_URI | optionnel, si l'API est derrière un autre nom d'hôte |
| GMAIL_PUBSUB_TOPIC, PUBSUB_PUSH_SA_EMAIL, PUBSUB_AUDIENCE | notifications Gmail (optionnel) |
| GMAIL_QUOTA_PER_MINUTE | optionnel, 3000 par défaut |
| ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_REPLY_MODEL | IA de la messagerie (optionnel) |

Cloudflare Pages (frontend) : `REACT_APP_BACKEND_URL`.

Dans Emergent uniquement (valeurs par défaut) : `STORAGE_PROVIDER=emergent`, `EMAIL_PROVIDER=emergent`, `EMERGENT_LLM_KEY`, `EMERGENT_EMAIL_KEY`, `INTEGRATION_PROXY_URL`.

## 10. Tests de contrôle

1. `https://api.exclusivity-events.com/api/health` répond `{"status":"ok"}`.
2. Connexion sur `https://app.exclusivity-events.com`, puis rechargement d'une page profonde (ex. `/lieux`).
3. Téléverser une photo de lieu, la rouvrir.
4. Télécharger un PDF de devis ; envoyer un devis par e-mail à sa propre adresse.
5. Signer une livraison de test et ouvrir le bon PDF.
6. Lancer à la main le workflow « Tâches planifiées » dans GitHub et vérifier qu'il se termine en vert.

| CRM_LEADS_API_KEY, CRM_LEADS_ORG_SLUG, APP_URL | Webhook du site vers le CRM, lien du devis dans les relances (optionnel) |
| INBOUND_PARSE_MODEL | Modèle Claude de la saisie rapide (optionnel) |
| CLAUDE_EXTRACT_MODEL | Modèle Claude de l'extraction des justificatifs / factures d'achat et de l'ajout rapide de tâche (optionnel) |

## Portails (espace client, portail prestataire)

Variables : `FILE_SIGNING_SECRET` (liens de fichiers signés, 5 min ; `openssl rand -hex 32`), `STAFF_2FA_REQUIRED` (`true` = admin et gérant bloqués sans double authentification), `API_RATE_LIMIT` (défaut 120 requêtes/min par utilisateur), `PUBLIC_RATE_LIMIT` (défaut 30/min par adresse IP sur les formulaires publics), `APP_URL` (liens des e-mails planifiés), `CORS_ORIGINS` (mettre l'URL exacte du site, pas `*`).

Réglages à faire dans le tableau de bord Clerk :
1. User & authentication → Email : activer « Email verification link » et « Email verification code » pour la connexion ; rendre le mot de passe facultatif.
2. Multi-factor : activer « Authenticator application (TOTP) » et « Backup codes ». Ne PAS cocher l'obligation globale (elle s'appliquerait aussi aux clients) : l'obligation pour admin et gérant est faite par l'application avec `STAFF_2FA_REQUIRED=true`.
3. Restrictions : désactiver l'inscription libre si seuls les invités doivent pouvoir créer un compte.

La limite de débit est en mémoire, par processus : avec plusieurs instances, la limite réelle est multipliée d'autant.

## Ma musique (module DJ)

Facultatif : `SPOTIFY_CLIENT_ID` et `SPOTIFY_CLIENT_SECRET` (developer.spotify.com → Dashboard → Create app, type Web API, aucun redirect nécessaire) activent la recherche de titres et l'import de playlists publiques ; `YOUTUBE_API_KEY` (Google Cloud → API YouTube Data v3 → identifiant « clé API ») active l'import de playlists YouTube. Sans ces clés, le module fonctionne en saisie manuelle et par liens. Spotify restreint l'accès aux playlists et aux extraits pour les nouvelles applications : l'import peut être refusé selon le statut de l'application Spotify, le lien est alors gardé en référence.

## Staff & missions

`STAFF_ENCRYPTION_KEY` (obligatoire pour l'IBAN et le n° de sécurité sociale, chiffrés au repos ; générer une clé Fernet et la conserver : la perdre rend ces données illisibles). Inscription autonome : la page `/rejoindre?o=<identifiant société>` utilise l'inscription Clerk (code e-mail) : l'inscription doit donc rester ouverte dans Clerk. Notifications : e-mail uniquement (pas de push web).
