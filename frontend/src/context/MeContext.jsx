import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useAuth } from "@clerk/react";
import { api, setTokenGetter } from "@/lib/api";

const MeContext = createContext(null);

export function MeProvider({ children }) {
  const { getToken } = useAuth();
  const [me, setMe] = useState(null);
  const [error, setError] = useState(false);

  const reload = useCallback(async () => {
    try {
      const { data } = await api.get("/me");
      setMe(data);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    setTokenGetter(() => getToken());
    reload();
  }, [getToken, reload]);

  useEffect(() => {
    const onFocus = () => document.visibilityState === "visible" && reload();
    const id = setInterval(onFocus, 45000);
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(id); window.removeEventListener("focus", onFocus); };
  }, [reload]);

  const can = useCallback((p) => !!me?.perms?.includes(p), [me]);
  const modules = me?.org?.modules || [];
  return <MeContext.Provider value={{ me, error, reload, can, modules, org: me?.org }}>{children}</MeContext.Provider>;
}

export const useMe = () => useContext(MeContext);
