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
  nav: { label: string; to: string }[];
};
