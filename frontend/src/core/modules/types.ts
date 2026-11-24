import type { ComponentType, LazyExoticComponent } from "react";

/**
 * Contrat d'un module frontend. Un module = un dossier src/modules/<clé>/ avec module.tsx.
 * La clé DOIT être identique à celle du manifeste backend : c'est le serveur
 * qui décide (via /api/me) si le module est visible pour l'utilisateur.
 */
export type FrontModule = {
  key: string;
  label: string;
  category: "core" | "ventes" | "operations" | "metiers" | "gestion";
  order?: number;
  routes: { path: string; component: LazyExoticComponent<ComponentType> }[];
  /** soon : entrée visible mais désactivée (fonction à venir) */
  nav: { label: string; to: string; soon?: boolean }[];
  /** Outils affichés dans l'en-tête (ex. notifications du module) */
  headerTools?: LazyExoticComponent<ComponentType>;
  /** Espace externe (portail) servi par ce module pour ces rôles : client, partner, organizer */
  portal?: { roles: string[]; component: LazyExoticComponent<ComponentType> };
};
