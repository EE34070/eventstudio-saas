import { lazy } from "react";
import type { FrontModule } from "@/core/modules/types";

/** Module métier : n'apparaît que si le plan de l'organisation l'inclut. */
const mod: FrontModule = {
  key: "dj",
  label: "DJ",
  category: "metiers",
  routes: [{ path: "/dj", component: lazy(() => import("./DjHome")) }],
  nav: [{ label: "DJ & playlists", to: "/dj" }],
};
export default mod;
