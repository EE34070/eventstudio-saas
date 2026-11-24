import { lazy } from "react";
import type { FrontModule } from "@/core/modules/types";

/** Module métier Wedding planner : espace de l'organisatrice + espace privé des mariés (rôle client). */
const mod: FrontModule = {
  key: "wedding_planner",
  label: "Wedding planner",
  category: "metiers",
  order: 10,
  routes: [
    { path: "/mariages", component: lazy(() => import("./pages/Dashboard")) },
    { path: "/mariages/reglages", component: lazy(() => import("./pages/Settings")) },
    { path: "/mariages/:id", component: lazy(() => import("./pages/WeddingFile")) },
  ],
  nav: [
    { label: "Mariages", to: "/mariages" },
    { label: "Prestataires", to: "/mariages/prestataires", soon: true },
    { label: "Paramètres", to: "/mariages/reglages" },
  ],
  headerTools: lazy(() => import("./components/NotificationsTool")),
  portal: { roles: ["client"], component: lazy(() => import("./couple/CoupleApp")) },
};
export default mod;
