# Architecture

## Principes

- Multi-sociétés : **une base MongoDB par société** (`t_<org_id>`) et une base plateforme (`orgs`, `users`…), routées automatiquement par `backend/tenant_router.py` (voir `docs/SAAS.md`). Chaque document porte aussi `org_id`, et toutes les lectures et écritures passent par le contexte de requête (`core.Ctx`) qui filtre sur la société de l'utilisateur : double cloisonnement.
- Identifiants : champ `id` (UUID en texte) ; l'`_id` MongoDB n'est jamais renvoyé.
- Dates : chaînes ISO. Les dates d'événement sont en heure locale (`AAAA-MM-JJTHH:MM`).
- Fichiers : stockés hors base ; les documents y font référence par `file:<id>`.

## Modèle de données (collections MongoDB)

| Collection | Champs principaux |
| --- | --- |
| `orgs` | id, slug, name, legal_name, siret, vat_number, address, zip, city, phone, email, iban, payment_terms, legal_mentions, terms, signature_fields, quote_prefix, invoice_prefix, default_vat, deposit_percent, modules, auto_reminders |
| `users` | user_id (Clerk), email, name, org_id, role, team_id, env |
| `team` | id, org_id, name, email, phone, job, access_role, skills, color, day_rate, active, unavailabilities, user_id |
| `contacts` | id, org_id, kind, status, first_name, last_name, company, email, phone, address, city, source, tags, notes, interactions |
| `venues` | id, org_id, name, type, address, zip, city, lat, lng, capacity, contact_*, truck_access, electricity, sound_limiter, setup_hours, teardown_hours, photos, plans, sections [{id, name, notes}], notes |
| `equipment` | id, org_id, ref, name, category, photo, description, qty_total, qty_maintenance, price_day, replacement_value, weight_kg, volume_m3, state, maintenance_log |
| `packs` | id, org_id, name, module, description, price, items, services, options, active |
| `events` | id, org_id, code, title, type, status, client_id, venue_id, start, end, setup_start, return_end, rental_start, rental_end, rental_days, guests, budget, chef_projet_id, vehicle_id, prestations, equipment [{equipment_id, qty, price_day, section_id}], team, planning, material_returned, deposit_paid, invoice_paid, extra_costs, amount_*, history |
| `quotes` | id, org_id, number, event_id, client_id, client, status, date, valid_until, lines [{label, description, qty, unit_price, vat, equipment_id}], deposit_percent, vat_breakdown, total_ht, total_vat, total_ttc, share_token, sent_at, sent_to, signature {request_id, status, signed_file, answers}, history |
| `invoices` | id, org_id, number, kind (acompte / solde), quote_id, event_id, client, status, date, due_date, lines, totaux, payments, paid_amount, balance_due, reminders, auto_level, share_token, history |
| `vehicles` | id, org_id, name, plate, capacity_kg, volume_m3, active |
| `loadings` | id, org_id, day, event_id, vehicle_id, status, lines [{equipment_id, qty, loaded_qty, missing_qty, note}] |
| `deliveries` | id, org_id, day, event_id, venue, lines, order, photos, status, signer_name, signed_at, notes, signature_file, bon_file |
| `files` | id, org_id, storage_path, filename, content_type, size, is_deleted |
| `counters` | org_id, key, seq (numérotation des événements, devis, factures) |
| `cron_runs`, `webhook_events` | clés d'idempotence des tâches planifiées et des webhooks |

Statuts d'événement : demande, devis_envoye, confirme, en_preparation, realise, facture, cloture.

## Routes API (préfixe `/api`)

**Compte et société** — `routes_main.py`, `clerk_auth.py`
- GET `/clerk/config`, GET `/me`, POST `/onboarding`
- GET, PUT `/org` · PUT `/org/modules`
- GET `/users` · PATCH `/users/{user_id}/role`

**Équipe, contacts, lieux** — `routes_main.py`
- GET, POST `/team` · PUT, DELETE `/team/{id}` · GET `/team/{id}/missions`
- GET, POST `/contacts` · GET, PUT, DELETE `/contacts/{id}` · POST `/contacts/{id}/interactions`
- GET, POST `/venues` · GET, PUT, DELETE `/venues/{id}` · GET `/geocode`

**Catalogue et matériel** — `routes_ops.py`
- GET, POST `/equipment` · PUT, DELETE `/equipment/{id}` · GET `/equipment/{id}/bookings` · POST `/equipment/{id}/maintenance`
- GET, POST `/packs` · PUT, DELETE `/packs/{id}`

**Événements, planning, tableau de bord** — `routes_ops.py`
- GET, POST `/events` · GET, PATCH, DELETE `/events/{id}` · GET `/events/overlaps`
- POST `/events/{id}/status` · POST `/events/{id}/shift`
- GET `/dashboard` · GET `/notifications` · GET `/search`

**Devis, factures, paiements** — `routes_billing.py`
- GET `/quotes` · POST `/events/{id}/quotes` · PUT `/quotes/{id}` · POST `/quotes/{id}/status` · POST `/quotes/{id}/share` · GET `/quotes/{id}/pdf`
- GET `/invoices` · POST `/quotes/{id}/invoice` · GET `/invoices/{id}/pdf`
- POST `/invoices/{id}/payments` · DELETE `/invoices/{id}/payments/{pid}`

**Envoi, signature, relances** — `routes_comms.py`
- POST `/quotes/{id}/send`
- POST `/quotes/{id}/signature` · POST `/quotes/{id}/signature/refresh` · POST `/quotes/{id}/signature/cancel` · GET `/quotes/{id}/signed-pdf`
- GET `/reminders` · PUT `/reminders/settings` · POST `/invoices/{id}/remind`

**Chargement et véhicules** — `routes_billing.py`
- GET, POST `/vehicles` · PUT `/vehicles/{id}`
- GET `/loading` · PATCH `/loading/{id}/lines/{equipment_id}` · PUT `/loading/{id}/vehicle` · POST `/loading/{id}/status`

**Livraison et implantation** — `routes_delivery.py`
- GET `/deliveries` · PUT `/deliveries/order` · POST `/deliveries/{id}/photos` · POST `/deliveries/{id}/sign`
- GET `/events/{id}/documents` · GET `/events/{id}/implantation/pdf`

**Fichiers** — `routes_files.py`
- POST `/files` · GET `/files/{id}`

**Routes publiques (sans connexion, protégées par jeton)**
- GET `/public/quotes/{token}` · GET `/public/quotes/{token}/pdf` · GET `/public/quotes/{token}/files/{id}`
- GET `/public/invoices/{token}/pdf`

**Routes machine**
- POST `/cron/loading`, POST `/cron/reminders` : secret `WEBHOOK_CRON_SECRET` en en-tête Bearer
- POST `/webhooks/yousign` : signature HMAC avec `YOUSIGN_WEBHOOK_SECRET`

## Rôles et règles d'accès

Six rôles, définis dans `core.py`. Un nouvel utilisateur est technicien par défaut.

| Permission | Admin | Gérant | Chef de projet | Commercial | Comptable | Technicien |
| --- | --- | --- | --- | --- | --- | --- |
| Événements : lire | ✔ | ✔ | ✔ | ✔ | ✔ | ses missions |
| Événements : modifier | ✔ | ✔ | ✔ | ✔ | | |
| Événements : supprimer | ✔ | ✔ | | | | |
| Finances : lire (devis, factures, montants) | ✔ | ✔ | ✔ | ✔ | ✔ | |
| Finances : écrire (factures, paiements, relances) | ✔ | ✔ | | | ✔ | |
| Catalogue : lire | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Catalogue : modifier (et véhicules) | ✔ | ✔ | ✔ | | | |
| Contacts : lire | ✔ | ✔ | ✔ | ✔ | ✔ | |
| Contacts : modifier | ✔ | ✔ | ✔ | ✔ | | |
| Lieux : lire | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Lieux : modifier | ✔ | ✔ | ✔ | ✔ | | |
| Équipe : lire | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Équipe : modifier | ✔ | ✔ | | | | |
| Société et utilisateurs | ✔ | ✔ | | | | |

Règles particulières :
- Le technicien ne voit que les événements, chargements et livraisons où il est affecté ; il peut cocher un chargement, ajouter des photos et faire signer une livraison.
- Créer et modifier un devis demande « événements : modifier » ou « finances : écrire » ; émettre une facture et enregistrer un paiement demande « finances : écrire ».
- Un devis facturé, en cours de signature ou signé ne peut plus être modifié.
- Un même matériel ne peut pas être réservé au-delà du stock sur des périodes qui se chevauchent.
- Un événement ne peut être clôturé que si le matériel est revenu et les factures soldées.
- Les montants et données financières sont retirés des réponses pour les rôles sans « finances : lire ».
