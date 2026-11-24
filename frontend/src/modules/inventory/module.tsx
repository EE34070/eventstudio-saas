import { lazy } from "react";
import type { FrontModule } from "@/core/modules/types";

const mod: FrontModule = {
  key: "inventory",
  label: "Stock & matériel",
  category: "operations",
  routes: [{ path: "/inventory/warehouses", component: lazy(() => import("./pages/WarehousesPage")) }],
  nav: [{ label: "Entrepôts", to: "/inventory/warehouses" }],
};
export default mod;
