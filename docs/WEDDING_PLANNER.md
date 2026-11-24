# Module Wedding planner (phase 1 + Repas et boissons)

Spécification de référence : prompt « Phase 1 : fondations » validé par Manon le 24/11/2026 et sa maquette interactive.

## Ce qui est livré

| Domaine | Backend (`app/modules/wedding_planner`) | Frontend (`src/modules/wedding_planner`) |
|---|---|---|
| Tableau de bord | `GET /wedding-planner/weddings` (cartes, avancement, blocs « à venir ») | `pages/Dashboard.tsx` |
| Nouveau mariage | `POST /weddings` : fiche, contacts du socle, événements, invitations | `components/NewWeddingModal.tsx` |
| Fiche informations | `PUT /weddings/{id}/info`, « même adresse », confession si religieuse | `components/InfoForm.tsx` (partagé admin / mariés) |
| Événements | `PUT /weddings/{id}/events` : Jour J obligatoire, Welcome dinner, Brunch, « Autre » ; estimation + nombre confirmé (Guest List) ; copie dans le module Événements du socle | `components/EventsTab.tsx` |
| Questionnaire | Google Forms API par compte de service ; questions identifiées par itemId ; table de correspondance éditable ; « À classer » avec suggestion ; questions renommées / supprimées ; réponses rattachées par e-mail ou à la main ; fiche = référence, différences à trancher | `components/QuestionnaireTab.tsx`, `pages/Settings.tsx` |
| Récapitulatif | 12 rubriques éditables ; IA (Anthropic) par rubrique, repli sans IA ; régénération sans écraser les passages modifiés ; PDF | `components/RecapTab.tsx` |
| Repas et boissons | un bloc par événement ; quantités = invités × ratio ; notes internes jamais visibles ; PDF traiteur | `components/FoodAdmin.tsx`, `couple/CoupleApp.tsx` |
| Compte et droits | invitations (statut, renvoi), langue, 5 interrupteurs, rubriques ouvertes | `components/AccountTab.tsx` |
| Notifications | génériques (types déclarés dans `seed.py`), dans l'espace et par e-mail, paramétrables | `components/NotificationsTool.tsx`, `pages/Settings.tsx` |
| Espace des mariés | `/api/portal/wedding/*` : jamais de notes, récapitulatif, budget ou tarifs masqués | `couple/CoupleApp.tsx` (FR/EN) |

## Socle : ajouts transverses

- `platform/invitations.py` : invitations des comptes externes (jeton haché, 30 jours, hook par module). Collection plateforme `invitations`.
- `platform/mailer.py` : e-mails via Resend ; sans clé, rien n'est envoyé (dev, tests).
- `core/provisioning.py` : migration `_m002_wedding_planner` (collections et index des sociétés existantes).
- `core/rbac.py` : `wedding_planner:*` pour le rôle manager.
- Frontend : mise en page `focus` (branding.layout), thème de l'organisation (`core/layout/theme.ts`), portail par module (`FrontModule.portal`), route `/invitation/:token`, mode démo (`npm run build:demo`).

## Configuration de l'organisation de Manon

Plan `pro` ou supérieur (ou `essentiel` avec `metier_modules: ["wedding_planner"]`), et `branding` :

```json
{"app_name": "Manon Jeanjean", "layout": "focus", "home_path": "/mariages",
 "primary_color": "#1F3D2B", "background": "#F2F1EB", "surface": "#FAF9F5", "ink": "#4b5c4c",
 "muted": "#6b7a63", "line": "#cdd6c6", "soft": "#a9c0ac", "alert": "#9a3b2e",
 "font_display": "Cormorant Garamond", "font_body": "Montserrat"}
```

## Variables d'environnement (Render)

| Variable | Rôle |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | compte de service Google (API Forms) ; partager le formulaire avec son e-mail |
| `RESEND_API_KEY`, `MAIL_FROM` | e-mails d'invitation et de notification |
| `APP_URL` | lien des invitations (`https://app.…`) |
| `ANTHROPIC_MODEL` | modèle du récapitulatif (défaut `claude-sonnet-5-5`) |

Côté Google Form : activer « Collecter les adresses e-mail » (rattachement automatique au couple).

## Limites connues / phases suivantes

- Nombre confirmé d'invités et contraintes alimentaires : point d'extension `service.confirmed_counts` et `diets`, branchés quand la Guest List (phase 2) existera.
- Prestataires, documents, paiements, tâches : cartes du tableau de bord prêtes (« À venir »).
- « Modifier mes réponses » : Google n'expose pas de lien d'édition par l'API ; le couple rouvre le formulaire (édition autorisée dans les réglages du Google Form).
- Crédits IA : compteur mensuel local au module (`wp_ai_usage`) en attendant un compteur commun du socle.
