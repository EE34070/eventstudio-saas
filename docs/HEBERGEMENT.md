# Hébergement — recommandations

## En bref

Gardez la stack actuelle (Cloudflare + Render + MongoDB Atlas + R2 + Clerk), mais **tout en Union européenne** pour le produit commercial, avec trois environnements séparés. Pas besoin de changer de fournisseurs : il faut changer de régions et de niveaux de service.

## 1. Le point bloquant : vos données sont aux États-Unis

La base actuelle d'Exclusivity Events est en Virginie (USA). C'est acceptable pour votre usage interne, mais pas pour vendre à des sociétés françaises : elles vous confient les données personnelles de leurs clients (mariés, invités, prestataires) et vous deviendrez leur **sous-traitant RGPD**. Les acheteurs et leurs avocats demanderont où sont les données.

À faire avant le premier client payant :

- Nouveau cluster Atlas sur **AWS Paris (eu-west-3)** ou Francfort, et migration des données d'Exclusivity Events au moment de la bascule.
- Nouveau bucket R2 avec la **juridiction UE**. La juridiction d'un bucket ne se change pas après création : il faut créer un bucket neuf et copier les fichiers.
- Services Render en région **Francfort**.
- Un **accord de sous-traitance (DPA)** à faire signer à vos clients, avec la liste de vos sous-traitants (Render, MongoDB, Cloudflare, Clerk, Stripe, Anthropic, e-mail).

Render, MongoDB, Cloudflare et Clerk sont des sociétés américaines : même en région UE, elles relèvent du droit américain (CLOUD Act). Avec des clauses contractuelles types et le cadre UE–États-Unis, c'est la norme pour un SaaS de PME. Si un jour un client exige un hébergeur souverain (collectivité, grand compte), prévoyez l'offre « Entreprise » sur un hébergeur européen (Scaleway, OVHcloud, Clever Cloud) : l'architecture le permet, inutile de le faire maintenant.

## 2. Architecture d'hébergement cible

| Composant | Service | Région | Niveau de départ | Pourquoi |
|---|---|---|---|---|
| Site vitrine | Webflow | CDN | votre plan actuel | `www.` : SEO, tarifs, inscription |
| Frontend | Cloudflare Pages | CDN mondial | gratuit / Pro | `app.` : très rapide, déploiement à chaque push, `_headers` de sécurité |
| API | Render Web Service (Docker) | Francfort | 2 instances Standard | `api.` : 2 instances = pas de coupure pendant les déploiements |
| Worker | Render Background Worker | Francfort | Starter | IA, OCR, synchronisations, relances hors de l'API |
| File de tâches / cache | Render Key Value (Redis) | Francfort | Starter | jobs, limitation de débit |
| Base de données | MongoDB Atlas dédié **M10** | AWS Paris | M10, sauvegarde continue | ressources dédiées, Performance Advisor, restauration à la minute |
| Fichiers | Cloudflare R2, juridiction UE | UE | à l'usage | pas de frais de sortie, URL signées |
| Identité | Clerk, instance Production | — | Pro | domaine `clerk.` personnalisé, connexion Google |
| E-mails transactionnels | Postmark ou Resend | UE si possible | entrée de gamme | SPF/DKIM/DMARC ; plus tard domaine d'envoi par organisation |
| Erreurs / disponibilité | Sentry (région UE) + Better Stack | UE | entrée de gamme | alerte avant que le client n'appelle |
| Paiements | Stripe (Billing, Tax, Connect) | — | à la transaction | abonnements et encaissements clients |
| DNS et domaine | Cloudflare | — | gratuit | domaine produit hors de Shopify, DNS + proxy + WAF au même endroit |

Le cluster Atlas dédié M10 démarre autour de 57 $ par mois ; un cluster Flex (entre 8 et 30 $ par mois) suffit pour la préproduction mais n'est pas fait pour la production. Chez Render, les services démarrent à 7 $ par mois pour 512 Mo, avec un abonnement d'espace de travail en plus du calcul.

### Ordre de grandeur du budget mensuel au lancement (à confirmer sur les grilles en vigueur)

| Poste | Estimation |
|---|---|
| Render (2 API Standard + worker + Redis + espace de travail) | 80 à 130 $ |
| MongoDB Atlas M10 production + Flex préproduction | 70 à 100 $ |
| Clerk Pro | 25 $ |
| Sentry, supervision, e-mails | 30 à 60 $ |
| Cloudflare (Pages, R2, DNS) | 0 à 25 $ |
| **Total hors IA** | **environ 200 à 350 $ / mois** |
| API Anthropic | variable : à refacturer via les crédits IA des plans |

Soit le prix de 3 à 5 abonnements Pro : le point mort d'infrastructure est atteint très tôt.

### Une base par société : réglages Atlas

- L'utilisateur de base de données de l'API doit pouvoir créer des bases (rôle `readWriteAnyDatabase` sur le cluster), car chaque inscription crée sa base.
- Surveillez le nombre de collections et d'index : environ 35 sociétés par cluster M10. Au-delà, passez en M30/M40 ou ajoutez un cluster dans `TENANT_CLUSTERS`.
- Les sauvegardes Atlas sont par cluster : pour restaurer une seule société, restaurez dans un cluster temporaire puis recopiez sa base.

## 3. Trois environnements

| | Développement | Préproduction (staging) | Production |
|---|---|---|---|
| Frontend | `npm run dev` | Cloudflare Pages (branche `staging` + aperçus par PR) | Pages, branche `main` |
| API / worker | local (docker compose) | Render, plans Starter | Render, Francfort |
| Base | Mongo local (replica set) | Atlas Flex, données fictives | Atlas M10 Paris |
| Fichiers | bucket `-dev` | bucket `-staging` | bucket `-prod` (juridiction UE) |
| Clerk | instance Development | instance Development | instance Production |
| Stripe | mode test | mode test | mode live |

Règles : jamais de données réelles hors production ; secrets différents par environnement ; tests d'isolation verts obligatoires avant tout déploiement en production (CI GitHub Actions fournie).

## 4. Domaines

- `www.votreproduit.com` : site vitrine (Webflow)
- `app.votreproduit.com` : application (Cloudflare Pages)
- `api.votreproduit.com` : API (Render, domaine personnalisé)
- `clerk.votreproduit.com` : authentification
- Plus tard : `client.votreproduit.com` ou domaines personnalisés par client (Cloudflare for SaaS) pour la marque blanche des espaces clients.

Exclusivity Events garde `app.exclusivity-events.com` le temps de la transition, puis peut pointer ce sous-domaine vers l'application commune avec sa propre marque.

## 5. Sauvegardes et reprise

- Atlas : sauvegarde continue avec restauration à un instant précis (M10+), rétention 7 jours minimum + instantané quotidien gardé 30 jours.
- Export chiffré quotidien vers un bucket R2 UE distinct (copie hors Atlas).
- Test de restauration en préproduction chaque trimestre, documenté.
- Objectifs annoncés aux clients : perte de données maximale 1 h, remise en service 4 h.

## 6. Quand monter en gamme

| Signal | Action |
|---|---|
| CPU Atlas > 60 % en continu, ou plus de 30 organisations actives | Atlas M20 puis M30 |
| Temps de réponse API p95 > 500 ms | API Render Pro ou 3 instances |
| File de jobs qui s'allonge (IA, synchronisation mail) | 2 workers, ou un worker dédié à l'IA |
| Client grand compte ou exigence contractuelle | Cluster dédié (offre Entreprise), éventuellement hébergeur souverain |

## 7. Ce qu'il ne faut pas faire

- Rester sur l'hébergement Emergent pour le produit commercial : pas de maîtrise des régions, des sauvegardes ni des coûts.
- Une base par client dès le départ : complexité de migration multipliée sans bénéfice à votre échelle. Gardez la base partagée cloisonnée, et le cluster dédié pour l'offre Entreprise.
- Stocker des fichiers dans MongoDB ou sur le disque des serveurs Render : toujours R2.
- Héberger le site vitrine dans l'application : Webflow pour le marketing, l'app pour le produit.
