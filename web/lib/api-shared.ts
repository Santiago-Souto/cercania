// Pieces shared by server calls (lib/api.ts) and browser calls (lib/send-report.ts, lib/client-api.ts, lib/auth.ts).
// No server-only imports here: this file is bundled into client components.

import { PERSONA_COOKIE } from "./persona";

export const USE_FAKE = process.env.NEXT_PUBLIC_USE_FAKE_DATA === "1";
/** The backend, called directly by server components (lib/api.ts). */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
/**
 * The backend as the browser sees it: a same-origin proxy (rewrite in next.config.ts). The session cookie set by
 * POST /auth/verify then belongs to the web origin, so server components can read it and forward it to the API.
 */
export const BROWSER_API_URL = "/api";

/** HttpOnly session cookie set by the backend (backend/app/deps.py). */
export const SESSION_COOKIE = "cercania_session";
/** Readable marker set by lib/auth.ts next to the session (which JS cannot read): the verified user's id.
 *  Never authoritative (the API trusts only the session); it keys per-user browser state and drops X-Person-Id. */
export const AUTH_FLAG_COOKIE = "cercania_auth";

// SIMULATED dev identity, used only when nobody is logged in: sent as `X-Person-Id`.
// The backend honors it only with ALLOW_DEV_IDENTITY_HEADER=1 (backend/app/deps.py). Fictional data only.
const DEV_PERSON_ID = process.env.NEXT_PUBLIC_DEV_PERSON_ID ?? "";

function readCookie(name: string): string | undefined {
  const m = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return m ? decodeURIComponent(m.slice(name.length + 1)) : undefined;
}

/** Browser only: the user id verified in this browser (lib/auth.ts), or undefined when nobody is logged in. */
export function loggedInUserId(): string | undefined {
  return typeof document === "undefined" ? undefined : readCookie(AUTH_FLAG_COOKIE) || undefined;
}

export function isLoggedIn(): boolean {
  return loggedInUserId() !== undefined;
}

// Browser identity headers. Logged in: none, the session cookie identifies the caller.
// Otherwise the persona picked in the demo bar (cookie, lib/persona.ts) wins over the env value.
// Server calls (lib/api.ts) decide from the request cookies themselves.
export function identityHeaders(): Record<string, string> {
  if (typeof document === "undefined") return DEV_PERSON_ID ? { "X-Person-Id": DEV_PERSON_ID } : {};
  if (isLoggedIn()) return {};
  const id = readCookie(PERSONA_COOKIE) || DEV_PERSON_ID;
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
