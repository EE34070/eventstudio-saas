# Sécurité — audit du 22/11/2026 et préparation de la mise en production

Périmètre : dépôt complet, backend FastAPI, frontend React. Tests faits dans la société QA et une société jetable TEST_SEC_ (supprimée). Aucune donnée de « Exclusivity Events » modifiée. Rien n'a été fait sur Render, Cloudflare, Clerk production ou le DNS.

## 1. Résultats

### Secrets et dépôt
- Fichiers suivis par git (322) : aucune clé réelle trouvée (Clerk, Anthropic, Resend, Google, Emergent, URI MongoDB avec mot de passe). Historique git : idem, seulement des exemples (`mongodb+srv://...` dans docs/DEPLOIEMENT.md).
- `backend/.env`, `frontend/.env`, `backups/` et `memory/test_credentials.md` n'ont jamais été commités et sont dans `.gitignore`. `memory/test_credentials.md` reste sur le disque de travail (les outils de test le lisent) mais hors dépôt.
- Trouvé : le mot de passe commun des comptes de test Clerk était écrit dans `scripts/qa_token.py`, `scripts/clerk_token.py`, `test_reports/iteration_2.json` et `iteration_3.json`. Retiré de ces fichiers ; les scripts créent maintenant un mot de passe aléatoire. Il reste dans l'historique git : supprimer les comptes de test Clerk avant la production (voir checklist).
- Les adresses `qa_*+clerk_test@example.com` et le code de test Clerk `424242` restent dans les tests et rapports : ils ne valent que sur une instance Clerk de développement.
- `scripts/clerk_ticket.py`, `qa_token.py`, `clerk_token.py` refusent de tourner si `ENV=production` ou si la clé Clerk est une clé live (vérifié).

### Environnements
- Variable `ENV` (development | staging | production), valeur inconnue = refus de démarrer.
- En production : `/docs`, `/redoc`, `/openapi.json` désactivés ; le serveur refuse de démarrer si `CORS_ORIGINS` contient `*` ou si `CLERK_AUTHORIZED_PARTIES` est vide (vérifié par import, pas sur Render).
- Aucune route de debug trouvée. Le démarrage ne crée aucune société ni donnée de démonstration ; il journalise une erreur si une société QA ou TEST_ existe en production.
- `scripts/purge_test_data.py` : simulation exécutée sur la base de prévisualisation (sociétés QA et TEST_ listées, rien supprimé). Le mode `--apply` n'a pas été exécuté.

### Authentification Clerk
- Toutes les routes `/api` passent par `need()` ou `current_member` (JWT vérifié par JWKS, signature RS256, expiration), sauf les 40 routes publiques listées en section 3.
- Ajouté : contrôle de l'émetteur (`CLERK_ISSUER`) et du domaine d'origine du jeton (`CLERK_AUTHORIZED_PARTIES`). Non testé avec un vrai jeton de production.
- Règle de connexion respectée : rien n'a été changé au parcours (une étape e-mail au plus, 2FA facultative, jamais par e-mail).

### Contrôle d'accès
- 470 routes inventoriées (section 4). 62 écritures sont déclarées avec une permission « read » : 33 vérifient le droit d'écriture dans la fonction (`quote_writer`, dont `POST /quotes/{qid}/send`), les autres sont des actions de terrain voulues (pointage de chargement, signature de livraison, tâches, notes de frais, musique) limitées aux événements de l'utilisateur.
- Corrigé : `POST /quotes/{qid}/signature/refresh` n'avait aucun contrôle d'écriture.
- Corrigé : `GET /equipment` renvoyait le nom des prestataires et les prix d'achat (`suppliers`, `cost_history`) à tous les rôles ayant le catalogue. Retirés pour tout rôle autre qu'Administrateur et Gérant.
- Toutes les requêtes passent par `Ctx.q()` qui impose l'`org_id` de la session.
- Tests (backend/tests/test_iter28_security.py, 9 réussis) : société A vers société B (lecture, écriture, envoi, listes), technicien vers finance et administration, client vers back-office et vers l'événement d'un autre client, prestataire vers back-office, absence de jeton, faux jeton : refus partout.

### Liens publics
- Jetons : 192 bits (devis, factures, suivi, vues) ou 256 bits (réponses prestataires). Les jetons iCal et musique sont stockés hachés.
- Ajouté : `X-Robots-Tag: noindex, nofollow` sur toutes les réponses de l'API et sur les pages publiques du frontend ; révocation du lien d'un devis (`POST /quotes/{qid}/share/revoke`) ; limite de débit des lectures publiques (60/min par adresse IP, 30/min pour les formulaires).
- Non fait : voir points restants (hachage, expiration).

### Durcissement HTTP
- En-têtes déjà présents : HSTS, nosniff, Referrer-Policy, X-Frame-Options DENY, Permissions-Policy, CSP stricte sur le JSON. Ajouté : `frontend/public/_headers` pour Cloudflare Pages (CSP du site en mode « rapport seul »).
- Limites de débit ajoutées : IA 20/min et envois 30/min par utilisateur. La connexion est limitée par Clerk.
- Uploads : type vérifié sur le contenu réel, 15 Mo, nom régénéré, accès par société. En production le bucket public (`S3_PUBLIC_BASE_URL`) est ignoré : liens signés de 5 minutes seulement.
- IA : consigne « le document est une donnée » ajoutée aux quatre extractions ; sorties relues par schéma ; aucune création sans validation de l'utilisateur.
- Corrigé : l'import de devis prestataire renvoyait le texte de l'erreur technique.

### Dépendances
- Python : starlette (9 avis) corrigé par fastapi 0.110 → 0.165 / starlette 1.10 ; pymongo 4.18.3 ; python-jose et ecdsa (vulnérables, non utilisés) retirés. La ligne litellm et emergentintegrations sont inchangées.
- Cette montée de version avait cassé la lecture de la grille de permissions (corrigé, et le serveur refuse maintenant de démarrer si la grille est vide). 161 tests de non-régression réussis ensuite. Non vérifié sur Render.
- Frontend : 10 avis « élevé », tous dans les outils de build de react-scripts (non livrés au navigateur). Non corrigés.

### Données
- `scripts/backup_mongo.py` : export chiffré vers R2. Sauvegarde puis restauration testées sur la base de prévisualisation, en local (78 collections, 9 558 documents relus à l'identique). Non testé sur Atlas ni sur R2.
- Journal d'audit déjà en place (12 mois). Ajouté au journal : révocation de lien, export et effacement RGPD.
- RGPD : `GET /contacts/{id}/gdpr-export` et `POST /contacts/{id}/gdpr-anonymize` (droit Membres & accès). API seulement, pas de bouton à l'écran.

## 2. Points restants

| Niveau | Point |
|---|---|
| Élevé | Les suites de tests d'accès plus anciennes (iter22, 25, 26) modifient encore des profils partagés de la société QA. L'isolation demandée (société, profils et utilisateurs propres à chaque test, base de test séparée) n'est pas faite. |
| Élevé | Mode production, contrôle de l'émetteur, du domaine et de `CLERK_JWKS_URL` : testés avec des clés simulées et en sous-processus, jamais sur Render avec la vraie instance Clerk. |
| Moyen | Isolation par société : vérifiée par tests croisés et par une recherche dans le code (47 appels sans filtre visible, relus : migrations de démarrage, recherches par empreinte de jeton, webhooks signés). Pas d'analyse statique automatique dans la CI. |
| Moyen | Limites de débit en mémoire du processus : valables avec une seule instance Render, remises à zéro à chaque redémarrage. |
| Moyen | Écrans des espaces client, prestataire et technicien non revus à l'œil ; seules leurs réponses d'API sont testées. |
| Moyen | CSP du site en « rapport seul ». Sauvegarde non planifiée et non testée sur Atlas / R2. |
| Moyen | Effacement RGPD : anonymise le contact, le compte et les messages du portail ; les playlists et les messages Gmail ne sont pas traités. |
| Faible | 10 avis « élevé » du frontend : tous dans react-scripts (body-parser, follow-redirects, launch-editor, svgo), outils de build et serveur de développement, aucun importé par `src/`. Non livrés au navigateur. |
| Faible | Export / effacement RGPD sans écran. Case « finance:costs » et bouton « Renvoyer un nouveau lien » non vus à l'écran. |
| Faible, corrigé | Mot de passe commun des comptes de test dans l'historique git : remplacé par un mot de passe aléatoire sur les 58 comptes de test de l'instance Clerk de développement ; `TEST_USERS_PASSWORD` lu depuis l'environnement ; `test_reports/` ignoré par git (59 anciens rapports restent suivis). |
| Élevé, corrigé | Prix d'achat, marges, fournisseurs : permission `finance:costs` (Administrateur, Gérant par défaut, attribuable par profil). Champs retirés de toutes les réponses JSON sans cette permission, routes Achats refusées. Test sur toutes les routes GET pour 6 rôles. |
| Élevé, corrigé | Jetons des liens publics : 256 bits, seule l'empreinte SHA-256 est en base. Expiration : devis à la date de validité (12 mois après signature), factures 12 mois, réponses prestataires date + 7 jours, invités fin de l'événement + 7 jours. « Renvoyer un nouveau lien » (Administrateur, Gérant). Les anciens liens sont invalidés. |
| Corrigé | `POST /quotes/{id}/signature/refresh` : tout rôle avec finance:read sans droit d'écriture pouvait relancer la lecture de l'état chez Yousign et faire passer le devis à « accepté » si la signature était terminée. |

## 3. Routes publiques (sans session)

| Route | Protection | Ce qu'elle expose |
|---|---|---|
| `/api/health`, `/api/languages`, `/api/clerk/config` | aucune | état, liste des langues, clé publique Clerk |
| `/api/__clerk/*` | relais Clerk, actif seulement en mode proxy | rien de l'application |
| `/api/auth/google/callback` | paramètre `state` aléatoire | retour OAuth Gmail |
| `/api/cron/*` (4) | secret `WEBHOOK_CRON_SECRET` | rien |
| `/api/webhooks/gmail`, `/api/webhooks/yousign` | jeton Google signé, signature HMAC | rien |
| `/api/crm/leads` | en-tête `X-API-Key` | création d'un prospect |
| `/api/public/quotes/{token}/*` (9), `/api/public/quote-views/{token}/*` (3) | jeton 192 bits | devis client sans coûts ni prestataire, PDF, signature par code |
| `/api/public/invoices/{token}/pdf` | jeton 192 bits | PDF de la facture |
| `/api/public/provider-requests/{token}` (3) | jeton 256 bits, expire à la date limite | demande de disponibilité d'un prestataire |
| `/api/public/tracking/{token}` | jeton 192 bits | suivi d'une livraison |
| `/api/public/music/{token}` (2) | jeton haché, question anti-robot | titre de l'événement, dépôt d'une suggestion |
| `/api/public/ical/{token}.ics` | jeton haché | missions d'un prestataire |
| `/api/portal/dl/{org}/{fid}` | signature HMAC, 5 minutes | un fichier |
| `/api/public/join/{org_id}`, `/api/public/legal/{org_id}/{page}` | identifiant de société | nom de la société, métiers, mentions légales |
| `/api/public/invitations/renew` | ticket Clerk d'origine, 1 envoi / 5 min | rien (renvoie un e-mail au membre) |

## 4. Tableau des routes

Les rôles indiqués sont ceux des profils par défaut ; la grille de chaque profil peut les restreindre. Les écritures déclarées avec un droit « read » vérifient le droit d'écriture dans la fonction ou sont des actions de terrain (voir §1).

| Méthode | Chemin | Permission | Filtre société | Rôles par défaut |
|---|---|---|---|---|
| DELETE | `/api/__clerk/{path:path}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/__clerk/{path:path}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| PATCH | `/api/__clerk/{path:path}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/__clerk/{path:path}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| PUT | `/api/__clerk/{path:path}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/access-profiles` | users:manage | oui (session) | admin, gerant |
| POST | `/api/access-profiles` | users:manage | oui (session) | admin, gerant |
| POST | `/api/access-profiles/activate` | users:manage | oui (session) | admin, gerant |
| DELETE | `/api/access-profiles/{pid}` | users:manage | oui (session) | admin, gerant |
| PUT | `/api/access-profiles/{pid}` | users:manage | oui (session) | admin, gerant |
| POST | `/api/applications/{aid}/{action}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/audit-logs` | users:manage | oui (session) | admin, gerant |
| GET | `/api/auth/google/callback` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/brand-templates` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/brand-templates` | org:write | oui (session) | admin, gerant |
| DELETE | `/api/brand-templates/{bid}` | org:write | oui (session) | admin, gerant |
| PUT | `/api/brand-templates/{bid}` | org:write | oui (session) | admin, gerant |
| GET | `/api/clerk/config` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| DELETE | `/api/client-documents/{did}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PATCH | `/api/client-documents/{did}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/contacts` | contacts:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/contacts` | contacts:write | oui (session) | admin, gerant, chef_projet, commercial |
| DELETE | `/api/contacts/{cid}` | contacts:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/contacts/{cid}` | contacts:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/contacts/{cid}` | contacts:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/contacts/{cid}/gdpr-anonymize` | users:manage | oui (session) | admin, gerant |
| GET | `/api/contacts/{cid}/gdpr-export` | users:manage | oui (session) | admin, gerant |
| POST | `/api/contacts/{cid}/interactions` | contacts:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/crm/config` | crm:manage | oui (session) | admin, gerant, commercial |
| PUT | `/api/crm/config` | org:write | oui (session) | admin, gerant |
| GET | `/api/crm/dashboard` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/leads` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/crm/opportunities` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities` | crm:manage | oui (session) | admin, gerant, commercial |
| GET | `/api/crm/opportunities/export.csv` | crm:manage | oui (session) | admin, gerant, commercial |
| DELETE | `/api/crm/opportunities/{oid}` | crm:manage | oui (session) | admin, gerant, commercial |
| GET | `/api/crm/opportunities/{oid}` | crm:manage | oui (session) | admin, gerant, commercial |
| PATCH | `/api/crm/opportunities/{oid}` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/activities` | crm:manage | oui (session) | admin, gerant, commercial |
| GET | `/api/crm/opportunities/{oid}/followup` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/followup` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/postpone` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/quotes` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/summary` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/tasks` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/crm/opportunities/{oid}/win` | crm:manage | oui (session) | admin, gerant, commercial |
| PATCH | `/api/crm/tasks/{tid}` | crm:manage | oui (session) | admin, gerant, commercial |
| POST | `/api/cron/loading` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/cron/messaging-daily` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/cron/messaging-sync` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/cron/reminders` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/dashboard` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/dashboard/extra` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/deliveries` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/deliveries/order` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/deliveries/{did}/photos` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/deliveries/{did}/sign` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/document-pages` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/document-pages` | org:write | oui (session) | admin, gerant |
| DELETE | `/api/document-pages/{pid}` | org:write | oui (session) | admin, gerant |
| PUT | `/api/document-pages/{pid}` | org:write | oui (session) | admin, gerant |
| POST | `/api/documents/extract` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/email-templates` | users:manage | oui (session) | admin, gerant |
| PUT | `/api/email-templates` | users:manage | oui (session) | admin, gerant |
| GET | `/api/equipment` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/equipment` | catalog:write | oui (session) | admin, gerant, chef_projet |
| DELETE | `/api/equipment/{eid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| PUT | `/api/equipment/{eid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/equipment/{eid}/bookings` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/equipment/{eid}/maintenance` | catalog:write | oui (session) | admin, gerant, chef_projet |
| PUT | `/api/equipment/{eid}/requirements` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/equipment/{eid}/stock` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/events/overlaps` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| DELETE | `/api/events/{eid}` | events:delete | oui (session) | admin, gerant |
| GET | `/api/events/{eid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/events/{eid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/events/{eid}/allocations` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/allocations/recalc` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/client-documents` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/events/{eid}/documents` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{eid}/implantation/pdf` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{eid}/logistics` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{eid}/logistics/generate` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/logistics/missions` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/events/{eid}/origin` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{eid}/portal` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/events/{eid}/portal` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/portal/invite` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/portal/messages` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PUT | `/api/events/{eid}/portal/modules/{key}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/events/{eid}/positions` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/events/{eid}/positions` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/events/{eid}/quote-candidates` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/events/{eid}/quotes` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{eid}/quotes` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/events/{eid}/quotes/attach` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/events/{eid}/requirements` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/events/{eid}/requirements` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{eid}/shift` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/events/{eid}/status` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{eid}/stock-return` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PUT | `/api/events/{eid}/timeline` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/events/{key}/music` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/events/{key}/music` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{key}/music/csv` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/import` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/moments/{mom}/comments` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{key}/music/pdf` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/resolve` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/events/{key}/music/search` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/send` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/suggestions/{sid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/template` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/unlock` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/events/{key}/music/validate` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/expenses` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/expenses` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| DELETE | `/api/expenses/{xid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/expenses/{xid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/expenses/{xid}/status` | finance:write | oui (session) | admin, gerant, comptable |
| POST | `/api/files` | connecté | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/files/{fid}` | connecté | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/files/{fid}/link` | connecté | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/gdpr-requests/{rid}/anonymize` | users:manage | oui (session) | admin, gerant |
| GET | `/api/geocode` | venues:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/health` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/inbound-requests` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/inbound-requests/availability` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/inbound-requests/parse` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/inbound-requests/settings` | org:write | oui (session) | admin, gerant |
| PUT | `/api/inbound-requests/settings` | org:write | oui (session) | admin, gerant |
| GET | `/api/inbound-requests/{rid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PATCH | `/api/inbound-requests/{rid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/inbound-requests/{rid}/convert` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/inbound-requests/{rid}/diff/{eid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/inbound-requests/{rid}/merge/{eid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/invoices` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/invoices/{iid}/payments` | finance:write | oui (session) | admin, gerant, comptable |
| DELETE | `/api/invoices/{iid}/payments/{pid}` | finance:write | oui (session) | admin, gerant, comptable |
| GET | `/api/invoices/{iid}/pdf` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/invoices/{iid}/remind` | finance:write | oui (session) | admin, gerant, comptable |
| POST | `/api/join` | connecté (sans société) | n/a | tout compte connecté |
| GET | `/api/languages` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/loading` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/loading/{lid}/lines/{equipment_id}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/loading/{lid}/status` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/loading/{lid}/vehicle` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/logistics/capacities` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/logistics/capacities` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/logistics/day` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/logistics/missions/{mid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/missions/{mid}/auto` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PATCH | `/api/logistics/missions/{mid}/items/{iid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/missions/{mid}/photos` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/missions/{mid}/place` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/logistics/missions/{mid}/sign` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/logistics/missions/{mid}/tracking-link` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/missions/{mid}/vehicles` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| DELETE | `/api/logistics/missions/{mid}/vehicles/{mvid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| PUT | `/api/logistics/missions/{mid}/vehicles/{mvid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/logistics/missions/{mid}/vehicles/{mvid}/loaded` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/missions/{mid}/wont-fit` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/logistics/reminders` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/logistics/reminders/rules` | org:write | oui (session) | admin, gerant |
| POST | `/api/logistics/reminders/run` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| DELETE | `/api/logistics/reminders/{lid}` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/logistics/reminders/{lid}/send` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/logistics/rotations` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/logistics/rotations` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/margin-rules` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/margin-rules` | org:write | oui (session) | admin, gerant |
| GET | `/api/me` | connecté (sans société) | n/a | tout compte connecté |
| GET | `/api/me/permissions` | connecté (sans société) | n/a | tout compte connecté |
| POST | `/api/members/{uid}/do/{action}` | users:manage | oui (session) | admin, gerant |
| GET | `/api/members/{uid}/handover` | users:manage | oui (session) | admin, gerant |
| POST | `/api/members/{uid}/handover` | users:manage | oui (session) | admin, gerant |
| GET | `/api/menu` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/menu/prefs` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/message-templates` | providers:manage | oui (session) | admin, gerant |
| PUT | `/api/message-templates` | providers:manage | oui (session) | admin, gerant |
| DELETE | `/api/messaging/account` | org:write | oui (session) | admin, gerant |
| GET | `/api/messaging/conversations` | messages:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| DELETE | `/api/messaging/conversations/{cid}` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/messaging/conversations/{cid}` | messages:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PATCH | `/api/messaging/conversations/{cid}` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/classify` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/contact` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/event` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/event-draft` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/notes` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/reply` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/restore` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/conversations/{cid}/suggest` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/messaging/gmail/connect` | org:write | oui (session) | admin, gerant |
| GET | `/api/messaging/messages/{mid}/attachments/{index}` | messages:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| DELETE | `/api/messaging/notes/{nid}` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/messaging/send` | messages:write | oui (session) | admin, gerant, chef_projet, commercial |
| PUT | `/api/messaging/settings` | org:write | oui (session) | admin, gerant |
| GET | `/api/messaging/status` | messages:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/messaging/sync` | messages:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/messaging/trash/purge` | org:write | oui (session) | admin, gerant |
| GET | `/api/missions` | providers:manage | oui (session) | admin, gerant |
| PATCH | `/api/missions/{mid}` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/missions/{mid}/dpae` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/modules` | connecté | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/music-plans` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/notifications` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/onboarding` | connecté (sans société) | n/a | tout compte connecté |
| GET | `/api/org` | connecté | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/org` | org:write | oui (session) | admin, gerant |
| PUT | `/api/org/menu-visibility` | org:write | oui (session) | admin, gerant |
| PUT | `/api/org/module-defaults` | org:write | oui (session) | admin, gerant |
| PUT | `/api/org/modules` | org:write | oui (session) | admin, gerant |
| GET | `/api/organizers` | contacts:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/organizers/ranking` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/packs` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/packs` | catalog:write | oui (session) | admin, gerant, chef_projet |
| DELETE | `/api/packs/{pid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| PUT | `/api/packs/{pid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/payroll-export` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/planning/assign` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/portal-modules` | users:manage | oui (session) | admin, gerant |
| PUT | `/api/portal-modules` | users:manage | oui (session) | admin, gerant |
| GET | `/api/portal-requests` | users:manage | oui (session) | admin, gerant |
| GET | `/api/portal-settings` | users:manage | oui (session) | admin, gerant |
| PUT | `/api/portal-settings` | users:manage | oui (session) | admin, gerant |
| GET | `/api/portal-users` | users:manage | oui (session) | admin, gerant |
| POST | `/api/portal-users/{uid}/{action}` | users:manage | oui (session) | admin, gerant |
| PATCH | `/api/portal/account` | portal:any | oui (session) | client / prestataire |
| POST | `/api/portal/account/delete-request` | portal:any | oui (session) | client / prestataire |
| GET | `/api/portal/account/export` | portal:any | oui (session) | client / prestataire |
| POST | `/api/portal/account/logout-all` | portal:any | oui (session) | client / prestataire |
| GET | `/api/portal/client/events` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}/billing` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}/documents` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}/documents/{did}/link` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}/messages` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{eid}/messages` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{eid}/timeline` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{eid}/timeline/comments` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{key}/music` | portal:client | oui (session) | client / prestataire |
| PUT | `/api/portal/client/events/{key}/music` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{key}/music/csv` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/import` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/moments/{mom}/comments` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{key}/music/pdf` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/resolve` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/client/events/{key}/music/search` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/send` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/suggestions/{sid}` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/template` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/unlock` | portal:client | oui (session) | client / prestataire |
| POST | `/api/portal/client/events/{key}/music/validate` | portal:client | oui (session) | client / prestataire |
| GET | `/api/portal/dl/{org_id}/{fid}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/portal/files` | portal:any | oui (session) | client / prestataire |
| GET | `/api/portal/me` | portal:any | oui (session) | client / prestataire |
| GET | `/api/portal/provider/agenda` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/applications/{aid}/reply` | portal:provider | oui (session) | client / prestataire |
| PUT | `/api/portal/provider/bank` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/busy` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/documents` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/documents` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/documents/{did}/link` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/home` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/ical/{action}` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions/{key}/music` | portal:provider | oui (session) | client / prestataire |
| PUT | `/api/portal/provider/missions/{key}/music` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions/{key}/music/csv` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/import` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/moments/{mom}/comments` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions/{key}/music/pdf` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/resolve` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions/{key}/music/search` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/send` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/suggestions/{sid}` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/template` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/unlock` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{key}/music/validate` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/missions/{mid}` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{mid}/confirm` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{mid}/invoice` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{mid}/make-invoice` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{mid}/messages` | portal:provider | oui (session) | client / prestataire |
| PUT | `/api/portal/provider/missions/{mid}/timesheet` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/missions/{mid}/withdraw` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/positions` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/positions/{pid}/apply` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/profile` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/profile/changes` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/requests` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/space` | portal:provider | oui (session) | client / prestataire |
| GET | `/api/portal/provider/unavailabilities` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/provider/unavailabilities` | portal:provider | oui (session) | client / prestataire |
| DELETE | `/api/portal/provider/unavailabilities/{uid}` | portal:provider | oui (session) | client / prestataire |
| POST | `/api/portal/terms` | portal:any | oui (session) | client / prestataire |
| PUT | `/api/positions/{pid}` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/positions/{pid}/duplicate` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/positions/{pid}/invite` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/product-documents` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/product-documents` | catalog:write | oui (session) | admin, gerant, chef_projet |
| DELETE | `/api/product-documents/{did}` | users:manage | oui (session) | admin, gerant |
| PATCH | `/api/product-documents/{did}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| POST | `/api/profile-changes/{cid}/{decision}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/provider-categories` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/provider-categories` | providers:manage | oui (session) | admin, gerant |
| PUT | `/api/provider-categories/{cid}` | providers:manage | oui (session) | admin, gerant |
| DELETE | `/api/provider-documents/{did}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/provider-invoices` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/provider-invoices/{iid}/paid` | providers:manage | oui (session) | admin, gerant |
| DELETE | `/api/provider-unavailabilities/{uid}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/providers` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/duplicates` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/export` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/providers/import` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/{pid}` | providers:manage | oui (session) | admin, gerant |
| PUT | `/api/providers/{pid}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/{pid}/bank` | users:manage | oui (session) | admin, gerant |
| POST | `/api/providers/{pid}/documents` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/{pid}/events` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/providers/{pid}/events/export` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/providers/{pid}/invite` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/providers/{pid}/unavailabilities` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/providers/{pid}/validate` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/public/ical/{token}.ics` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/invitations/renew` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/invoices/{token}/pdf` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/join/{org_id}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/legal/{org_id}/{page}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/music/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/music/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/provider-requests/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/provider-requests/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/provider-requests/{token}/unsubscribe` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quote-views/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quote-views/{token}/page-files/{fid}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quote-views/{token}/pdf` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quotes/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quotes/{token}/files/{fid}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/quotes/{token}/options` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quotes/{token}/page-files/{fid}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/quotes/{token}/pdf` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/quotes/{token}/refuse` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/quotes/{token}/sign/confirm` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/quotes/{token}/sign/request` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/public/quotes/{token}/viewed` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/public/tracking/{token}` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| GET | `/api/purchase-invoices` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/purchase-invoices` | finance:write | oui (session) | admin, gerant, comptable |
| DELETE | `/api/purchase-invoices/{pid}` | finance:write | oui (session) | admin, gerant, comptable |
| PUT | `/api/purchase-invoices/{pid}` | finance:write | oui (session) | admin, gerant, comptable |
| POST | `/api/quote-section-templates` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quote-templates` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quote-templates` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| DELETE | `/api/quote-templates/{tid}` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quote-templates/{tid}/use` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| DELETE | `/api/quote-views/{vid}` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/direct` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/quotes/{qid}` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/availability` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/compare` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/detach` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/duplicate` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/installation/pdf` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/quotes/{qid}/invoice` | finance:write | oui (session) | admin, gerant, comptable |
| POST | `/api/quotes/{qid}/new-version` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PATCH | `/api/quotes/{qid}/option` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/pages` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/quotes/{qid}/pages` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/pdf` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/send` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/share` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/signature` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/signature/cancel` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/signature/proof` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/signature/refresh` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/signed-pdf` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/status` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/structure` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/quotes/{qid}/structure` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/urgent-reminder` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/urgent-reminder` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/versions` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/quotes/{qid}/views` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/quotes/{qid}/views` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/reminders` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PUT | `/api/reminders/settings` | finance:write | oui (session) | admin, gerant, comptable |
| GET | `/api/requirement-templates` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/requirement-templates` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/search` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/service-requests` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/service-requests/prefill` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/service-requests/{rid}` | providers:manage | oui (session) | admin, gerant |
| PUT | `/api/service-requests/{rid}` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests/{rid}/cancel` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/service-requests/{rid}/candidates` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests/{rid}/preview` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests/{rid}/recipients/{cid}/remind` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests/{rid}/recipients/{cid}/retain` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/service-requests/{rid}/send` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/staff-teams` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/staff-teams` | providers:manage | oui (session) | admin, gerant |
| PUT | `/api/staff-teams/{tid}` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/staff/overview` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/staff/planning` | providers:manage | oui (session) | admin, gerant |
| GET | `/api/staff/stats` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/stock/availability` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/stock/import` | catalog:write | oui (session) | admin, gerant, chef_projet |
| POST | `/api/stock/inventory` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/stock/movements` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/stock/movements` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/stock/options` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/stock/settings` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/stock/settings` | org:write | oui (session) | admin, gerant |
| POST | `/api/stock/transfers` | catalog:write | oui (session) | admin, gerant, chef_projet |
| POST | `/api/stock/transfers/{mid}/receive` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/subscriptions` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/subscriptions` | finance:write | oui (session) | admin, gerant, comptable |
| DELETE | `/api/subscriptions/{sid}` | finance:write | oui (session) | admin, gerant, comptable |
| PUT | `/api/subscriptions/{sid}` | finance:write | oui (session) | admin, gerant, comptable |
| GET | `/api/supplier-quotes` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/supplier-quotes/extract` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| POST | `/api/supplier-quotes/import` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| PATCH | `/api/supplier-quotes/{sid}` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/supplier-quotes/{sid}/order-draft` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/tasks` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/tasks` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/tasks/quick` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| DELETE | `/api/tasks/{tid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PATCH | `/api/tasks/{tid}` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/team` | team:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/team` | team:write | oui (session) | admin, gerant |
| DELETE | `/api/team/{tid}` | team:write | oui (session) | admin, gerant |
| PUT | `/api/team/{tid}` | team:write | oui (session) | admin, gerant |
| POST | `/api/team/{tid}/dpae` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/team/{tid}/invite` | team:write | oui (session) | admin, gerant |
| GET | `/api/team/{tid}/invite-link` | team:write | oui (session) | admin, gerant |
| GET | `/api/team/{tid}/missions` | team:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| GET | `/api/timesheets` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/timesheets/validate` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/timesheets/{tid}/{action}` | providers:manage | oui (session) | admin, gerant |
| POST | `/api/translate` | events:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/users` | users:manage | oui (session) | admin, gerant |
| PUT | `/api/users/{user_id}/overrides` | users:manage | oui (session) | admin, gerant |
| PATCH | `/api/users/{user_id}/profile` | users:manage | oui (session) | admin, gerant |
| PATCH | `/api/users/{user_id}/role` | users:manage | oui (session) | admin, gerant |
| GET | `/api/vehicles` | events:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/vehicles` | catalog:write | oui (session) | admin, gerant, chef_projet |
| PUT | `/api/vehicles/{vid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/venues` | venues:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/venues` | venues:write | oui (session) | admin, gerant, chef_projet, commercial |
| DELETE | `/api/venues/{vid}` | venues:write | oui (session) | admin, gerant, chef_projet, commercial |
| GET | `/api/venues/{vid}` | venues:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| PUT | `/api/venues/{vid}` | venues:write | oui (session) | admin, gerant, chef_projet, commercial |
| PUT | `/api/venues/{vid}/logistics` | venues:write | oui (session) | admin, gerant, chef_projet, commercial |
| POST | `/api/venues/{vid}/spaces` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |
| GET | `/api/warehouses` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/warehouses` | catalog:write | oui (session) | admin, gerant, chef_projet |
| PUT | `/api/warehouses/{wid}` | catalog:write | oui (session) | admin, gerant, chef_projet |
| GET | `/api/warehouses/{wid}/stock` | catalog:read | oui (session) | admin, gerant, chef_projet, commercial, comptable, technicien |
| POST | `/api/webhooks/gmail` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/webhooks/yousign` | PUBLIC | jeton / secret / aucune donnée privée | tous |
| POST | `/api/{coll}/{did}/share/revoke` | finance:read | oui (session) | admin, gerant, chef_projet, commercial, comptable |

## 5. Checklist de mise en production (actions de votre côté)

### Render (exclusivity-events-api)
1. Ne changez pas la Build Command (index Emergent, ligne litellm exclue).
2. Environment : ajoutez `ENV=production`, `CORS_ORIGINS=https://<domaine de l'app>`, `CLERK_AUTHORIZED_PARTIES=https://<domaine de l'app>`, `CLERK_USE_PROXY=false`, `FILE_SIGNING_SECRET` (`openssl rand -hex 32`), `WEBHOOK_CRON_SECRET` (nouvelle valeur), `STAFF_ENCRYPTION_KEY`, `BACKUP_ENCRYPTION_KEY`, `STORAGE_PROVIDER=s3` et les `S3_*`, `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM`, `APP_URL`. Laissez `S3_PUBLIC_BASE_URL` vide.
3. Plus tard : `PENNYLANE_API_KEY`, sur Render uniquement, jamais dans Cloudflare Pages ni dans une variable `REACT_APP_*`. Aucun code ne l'utilise aujourd'hui.
4. Déployez, puis ouvrez `https://<api>/api/health` (doit répondre ok) et `https://<api>/docs` (doit répondre 404).
5. Créez un Cron Job quotidien : `python3 scripts/backup_mongo.py backup`. Une fois par mois : `python3 scripts/backup_mongo.py restore-test`.

### Cloudflare
1. Pages : variable `REACT_APP_BACKEND_URL=https://<api>`, puis redéployez. Vérifiez que `_headers` est pris en compte (onglet Réseau, en-tête `X-Frame-Options`).
2. R2 : bucket privé (accès public désactivé), jeton d'accès limité à ce bucket.

### Clerk
1. Créez l'instance Production, ajoutez le domaine, copiez `pk_live_` / `sk_live_` dans Render.
2. Restrictions : inscription fermée (mode invitation). Le flux prestataire passe par les invitations de l'application.
3. Connexion : e-mail + mot de passe et Google ; ne cochez pas « code par e-mail » comme second facteur ; 2FA par application ou passkey, facultative.
4. Relevez l'URL de l'émetteur (Frontend API) et mettez-la dans `CLERK_ISSUER` sur Render.

### DNS (Shopify, domaine exclusivity-events.com)
1. Ajoutez les CNAME demandés par Clerk (clerk, accounts, clkmail, clk._domainkey, clk2._domainkey).
2. Ajoutez le CNAME du sous-domaine de l'application vers Cloudflare Pages, et celui de l'API vers Render si vous voulez un domaine personnalisé.
3. Resend : ajoutez les enregistrements SPF (TXT) et DKIM fournis par Resend, puis un DMARC `v=DMARC1; p=none; rua=mailto:contact@exclusivity-events.com`. Passez à `p=quarantine` après deux semaines sans rejet.

### Données
1. Atlas : activez les sauvegardes (Cloud Backup) si votre offre le permet ; restreignez l'accès réseau aux adresses de Render.
2. Avant l'ouverture : `python3 scripts/purge_test_data.py --dry-run`, relisez, puis `--apply --yes`.
3. Supprimez les comptes `+clerk_test` de l'instance Clerk de développement.

### Secrets à régénérer avant la production
Aucun secret réel n'a été trouvé dans le dépôt. À régénérer parce qu'ils ont servi en développement ou transité par cet environnement : `CLERK_SECRET_KEY` (remplacée par la clé live), `WEBHOOK_CRON_SECRET`, `FILE_SIGNING_SECRET`, mot de passe de l'utilisateur MongoDB Atlas, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, clés R2, `YOUSIGN_API_KEY` et son secret de webhook, `GOOGLE_CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`, `CRM_LEADS_API_KEY`. Ne régénérez pas `STAFF_ENCRYPTION_KEY` si des IBAN sont déjà enregistrés en production.


## 6. À vérifier sur Render après déploiement

```
curl -s https://<api>/api/health                        # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" https://<api>/docs          # 404
curl -s -o /dev/null -w "%{http_code}\n" https://<api>/openapi.json  # 404
curl -s -o /dev/null -w "%{http_code}\n" https://<api>/api/events    # 401
curl -sI https://<api>/api/health | grep -iE "strict-transport|x-robots|x-frame|x-content-type"
curl -sI -H "Origin: https://evil.example" https://<api>/api/health | grep -i access-control   # aucune ligne
```
Puis : connexion réelle depuis le domaine de l'application ; `python3 scripts/backup_mongo.py backup` puis `restore-test` (Atlas vers R2) ; `python3 scripts/purge_test_data.py --dry-run` puis `--apply --yes`.

Variables obligatoires (le serveur refuse de démarrer sinon, message explicite) : `ENV=production`, `CORS_ORIGINS`, `CLERK_AUTHORIZED_PARTIES`, `CLERK_ISSUER`, `CLERK_JWKS_URL`, `FILE_SIGNING_SECRET`, `WEBHOOK_CRON_SECRET`, clé Clerk `sk_live_`, `MONGO_URL` non locale. `ENV` absente = règles de production. Les scripts de test et la suite pytest refusent de tourner hors `ENV=development`.

Clerk Production : domaine personnalisé, URL autorisées = domaine de l'application, inscription fermée, 2FA facultative par application ou passkey, durée de session 7 jours avec inactivité 24 h (réglable).

Audits à relancer chaque mois : `pip-audit -r backend/requirements.txt --disable-pip --no-deps` et `cd frontend && yarn audit --groups dependencies`. La CI (`.github/workflows/ci.yml`) les lance à chaque push.

## 7. Migrations de données

Depuis le 22/11/2026, aucune migration ne s'exécute au démarrage sans `RUN_MIGRATIONS=true`. Sans cette variable, le serveur journalise seulement la liste des migrations en attente.

- `python3 backend/migrations.py --dry-run` : nombre d'éléments concernés par migration et par société (la société réelle est signalée), sans rien écrire.
- `python3 backend/migrations.py --apply` : exécution dans l'ordre ; en production, sauvegarde chiffrée avant ; arrêt à la première erreur (les suivantes ne sont pas lancées) ; résultat écrit dans `schema_migrations` (identifiant, date, statut, nombre d'éléments par société) et dans le journal d'audit de chaque société.
- Limite : MongoDB sans transaction ici, une migration interrompue en cours peut avoir modifié une partie des éléments ; toutes sont idempotentes et peuvent être relancées.

| Identifiant | Effet |
|---|---|
| 001_roles_retires | Renomme les anciens rôles des comptes |
| 002_types_contacts | Ajoute le type « client » aux contacts sans type |
| 003_organisateurs | Remplace le métier prestataire « wedding planner » par les types d'organisateur |
| 004_taches_crm | Copie les anciennes tâches CRM dans la To-do |
| 005_entrepots | Crée l'entrepôt par défaut et les niveaux de stock |
| 006_blocs_devis | Convertit les lignes des anciens devis en blocs |
| 007_versions_devis | Numérote V1 les devis sans version |
| 008_liens_haches | Supprime les jetons de lien en clair |
| 009_grille_profils | Ajoute la grille aux profils d'accès et finance:costs au profil Gérant |
| 010_contacts_lieux | Convertit le contact unique d'un lieu en liste |
| 011_clients_evenements | Ajoute la liste des clients et la commission organisateur aux événements |

Ces onze migrations tournaient jusqu'ici à chaque démarrage, sur toutes les sociétés. Aucune n'est encore inscrite dans `schema_migrations`.
