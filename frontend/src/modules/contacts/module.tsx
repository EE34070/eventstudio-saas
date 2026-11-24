import { lazy } from "react";
import type { FrontModule } from "@/core/modules/types";

const mod: FrontModule = {
  key: "contacts",
  label: "Contacts",
  category: "core",
  order: 2,
  routes: [{ path: "/contacts", component: lazy(() => import("./pages/ContactsPage")) }],
  nav: [{ label: "Contacts", to: "/contacts" }],
};
export default mod;
