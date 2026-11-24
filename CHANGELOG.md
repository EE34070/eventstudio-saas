# Journal des modifications

## 2026-11-19 — Préparation du dépôt

État de l'application à cette date :

- Socle : authentification Clerk (Google, e-mail/mot de passe), multi-sociétés, six rôles, tableau de bord, événements, planning, catalogue et matériel, contacts, lieux, équipe, organisation.
- Devis et factures : TVA par ligne, acompte, PDF avec fiches produits, devis en ligne, facture d'acompte et de solde, paiements.
- Chargement du jour par véhicule et livraison du jour avec bon signé et photos.
- Envoi du devis par e-mail, relances d'impayés manuelles et automatiques.
- Lieux : plans, photos, espaces, plan d'implantation imprimable.
- Location de matériel sur une plage de dates, chevauchements d'événements.
- Signature électronique Yousign : code présent, jamais exécuté avec une clé réelle.

Dans cette version, sans changement fonctionnel :

- `.gitignore` complété (fichiers `.env`, journaux, fichiers téléversés).
- Ajout de `backend/.env.example` et `frontend/.env.example`.
- Ajout de `README.md`, `docs/ARCHITECTURE.md` et de ce journal.
- Dépendances inutilisées retirées du backend et du frontend ; un seul fichier de verrouillage (`frontend/yarn.lock`).
