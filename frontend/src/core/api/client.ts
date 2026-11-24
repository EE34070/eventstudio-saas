/**
 * Client API unique. Ajoute le jeton Clerk et l'organisation active (X-Org-Id).
 * Le serveur revalide toujours l'appartenance à l'organisation : l'en-tête n'est qu'un choix.
 */
const API_URL = import.meta.env.VITE_API_URL ?? "";

let tokenGetter: () => Promise<string | null> = async () => null;
let activeOrgId: string | null = null;

export function configureApi(opts: { getToken: () => Promise<string | null> }) {
  tokenGetter = opts.getToken;
}

export function setActiveOrg(orgId: string | null) {
  activeOrgId = orgId;
  try {
    if (orgId) localStorage.setItem("activeOrg", orgId);
  } catch {
    /* stockage indisponible : sans conséquence */
  }
}

export function storedOrg(): string | null {
  try {
    return localStorage.getItem("activeOrg");
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await tokenGetter();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (activeOrgId) headers.set("X-Org-Id", activeOrgId);

  const res = await fetch(`${API_URL}/api${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
