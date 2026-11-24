import type { FrontModule } from "./types";

/** Découverte automatique : chaque src/modules/<clé>/module.tsx est enregistré. */
const found = import.meta.glob<{ default: FrontModule }>("../../modules/*/module.tsx", { eager: true });

export const frontModules: FrontModule[] = Object.values(found)
  .map((m) => m.default)
  .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));

export const CATEGORY_LABELS: Record<FrontModule["category"], string> = {
  core: "Général",
  ventes: "Ventes",
  operations: "Opérations",
  metiers: "Métiers",
  gestion: "Gestion",
};
