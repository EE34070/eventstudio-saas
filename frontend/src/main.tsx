import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

// Mode démo (npm run build:demo) : vrais écrans, faux serveur en mémoire, sans Clerk ni API.
const Root = import.meta.env.VITE_DEMO === "1" ? lazy(() => import("@/demo/DemoApp")) : lazy(() => import("@/app/App"));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Suspense fallback={null}>
      <Root />
    </Suspense>
  </StrictMode>,
);
