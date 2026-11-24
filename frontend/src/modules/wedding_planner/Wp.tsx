import type { ReactNode } from "react";
import { useSession } from "@/core/session/SessionProvider";
import { brandingVars, loadBrandFonts } from "@/core/layout/theme";
import { Toaster } from "./ui";
import "./wp.css";

/** Racine de chaque page du module : thème de l'organisation + confirmations. */
export function Wp({ children }: { children: ReactNode }) {
  const { session } = useSession();
  loadBrandFonts(session.branding);
  return (
    <div className="wp" style={brandingVars(session.branding)}>
      {children}
      <Toaster />
    </div>
  );
}
