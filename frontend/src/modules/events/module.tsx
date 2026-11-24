import { lazy } from "react";
import type { FrontModule } from "@/core/modules/types";

const mod: FrontModule = {
  key: "events",
  label: "Événements",
  category: "core",
  order: 1,
  routes: [{ path: "/events", component: lazy(() => import("./pages/EventsPage")) }],
  nav: [{ label: "Événements", to: "/events" }],
};
export default mod;
