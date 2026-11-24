# Module Wedding planner

Module métier `wedding_planner` (à cocher dans Paramètres › Modules de la société). Spécification : prompt « Phase 1 : fondations » validé par Manon le 24/11/2026, et sa maquette.

## Ce que fait le module

| Domaine | Backend | Frontend |
|---|---|---|
| Tableau de bord des mariages | `GET /api/wedding/weddings` | `src/wedding/Dashboard.jsx` (`/mariages`) |
| Nouveau mariage | `POST /api/wedding/weddings` : fiche, contacts, événements, invitations | modale du tableau de bord |
| Fiche informations | `PUT /api/wedding/weddings/{id}/info` | `src/wedding/InfoForm.jsx` (partagé organisatrice / mariés) |
| Événements du week-end | `PUT …/events` : Jour J obligatoire, Welcome dinner, Brunch, « Autre » | onglet Événements |
| Questionnaire Google Form | `wedding_core.sync` (toutes les 15 min + bouton) ; `…/questionnaire`, `/api/wedding/questions`, réponses à attribuer | onglet Questionnaire, `src/wedding/Settings.jsx` |
| Récapitulatif | `…/recap`, `…/recap/generate`, PDF | onglet Récapitulatif |
| Repas et boissons | `…/food/{événement}`, PDF traiteur | onglet Repas et boissons |
| Compte et droits | invitations, langue, 5 droits, rubriques ouvertes | onglet Compte et droits |
| Notifications | `/api/wedding/notifications`, préférences dans Paramètres | bouton Notifications |
| Espace des mariés | `/api/portal/wedding/*` (rôle client) | `src/wedding/CoupleSpace.jsx`, ouvert depuis le portail client |

## Branchements sur l'existant (une seule saisie)

- Les partenaires sont des **contacts** (type client).
- Chaque événement activé et daté est un **événement** de l'application (type Mariage), avec le couple en contacts clients : devis, DJ, logistique et espace client classique (documents, devis et factures, musique, messages) fonctionnent comme pour tout événement. Le champ `wedding_id` de l'événement renvoie au mariage.
- Les **invitations** passent par le portail client existant (`portal_core.invite` : compte Clerk, lien de connexion, e-mail via la messagerie Gmail connectée ; sinon le lien est affiché pour être transmis).
- Droits : rubrique « Événements » de la grille d'accès (`access_grid` : `wedding` → `events`).

## Données (base de la société)

`wp_weddings`, `wp_settings`, `wp_questions` (id = itemId Google), `wp_responses` (id = responseId Google), `wp_recaps`, `wp_food`, `wp_notifications`.

## Configuration

| Variable | Rôle |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | compte de service Google (API Forms, lecture) ; partager le formulaire avec son adresse e-mail |
| `ANTHROPIC_API_KEY` / `LLM_API_KEY` | synthèse IA du récapitulatif (sinon synthèse simple question / réponse) |
| `APP_URL` | liens d'invitation |

Côté Google Form : activer « Collecter les adresses e-mail » (rattachement automatique au couple).
Charte de l'espace : vert #1F3D2B, crème, Cormorant Garamond + Montserrat par défaut ; modifiable par société dans `orgs.wp_branding`.

## Tests

`backend/tests_saas/test_wedding.py` (8 tests : création, cloisonnement, droits des mariés, synchronisation et adaptabilité du formulaire, préremplissage, réponses à attribuer, récapitulatif, repas et boissons, règles des événements).

## Phases suivantes

Guest List (nombre confirmé d'invités, contraintes alimentaires : point d'extension `wedding_core.confirmed_counts`), prestataires, documents, paiements, tâches, planning, musique, design et ambiance.
