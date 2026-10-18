// Pieces shared by server calls (lib/api.ts) and browser calls (lib/send-report.ts, lib/client-api.ts).
// No server-only imports here: this file is bundled into client components.

// Server components call the backend directly and forward the session cookie (lib/api.ts).
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

// The browser calls the backend through the same-origin rewrite in next.config.ts, so the session
// cookie set by POST /auth/verify is first-party on the web origin. Web and API are different sites
// on Render (onrender.com is a public suffix), where a cross-site cookie would be blocked.
export const BROWSER_API = "/api";

/** Name of the httpOnly session cookie the backend sets (backend/app/deps.py SESSION_COOKIE). */
export const SESSION_COOKIE = "cercania_session";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    /** Extra error data, e.g. `current` on an admin 409 overwrite warning (CIA-48). */
    public current?: unknown,
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
    body?.error?.current,
  );
}

/** Browser only: the session is missing or expired, go log in again and come back here afterwards. */
export function onUnauthorized(): void {
  const next = window.location.pathname + window.location.search;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = `/login?mode=login&next=${encodeURIComponent(next)}`;
}
