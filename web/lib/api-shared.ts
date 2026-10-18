// Pieces shared by server calls (lib/api.ts) and browser calls (lib/send-report.ts).
// No server-only imports here: this file is bundled into client components.

import { PERSONA_COOKIE } from "./persona";

export const USE_FAKE = process.env.NEXT_PUBLIC_USE_FAKE_DATA === "1";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

// SIMULATED until login lands (CIA-14 / CIA-32): who is calling, sent as `X-Person-Id`.
// The backend honors it only with ALLOW_DEV_IDENTITY_HEADER=1 (backend/app/deps.py). Fictional data only.
const DEV_PERSON_ID = process.env.NEXT_PUBLIC_DEV_PERSON_ID ?? "";

// In the browser the persona picked in the demo bar (cookie, lib/persona.ts) wins over the env value.
// Server calls (lib/api.ts) add the cookie themselves.
export function identityHeaders(): Record<string, string> {
  let id = DEV_PERSON_ID;
  if (typeof document !== "undefined") {
    const m = document.cookie.split("; ").find((c) => c.startsWith(`${PERSONA_COOKIE}=`));
    if (m) id = decodeURIComponent(m.split("=")[1]);
  }
  return id ? { "X-Person-Id": id } : {};
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export const NETWORK_ERROR_MESSAGE = "No pudimos conectar con el servidor. Revisá tu conexión y probá de nuevo.";

/** Turns a non-2xx response into an ApiError carrying the backend's message. */
export async function errorFrom(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  return new ApiError(
    body?.error?.code ?? "unknown",
    body?.error?.message ?? "No pudimos conectar con el servidor. Probá de nuevo.",
    res.status,
  );
}
