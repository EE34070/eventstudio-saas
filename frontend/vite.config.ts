import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => ({
  // Mode démo : chemins relatifs, pour être servi depuis n'importe quel dossier
  base: mode === "demo" ? "./" : "/",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: { sourcemap: false, chunkSizeWarningLimit: 600 },
}));
