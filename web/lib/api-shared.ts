// Pieces shared by server calls (lib/api.ts) and browser calls (lib/send-report.ts).
// No server-only imports here: this file is bundled into client components.

export const USE_FAKE = process.env.NEXT_PUBLIC_USE_FAKE_DATA === "1";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

// SIMULATED until login lands (CIA-14 / CIA-32): who is calling, sent as `X-Person-Id`.
// The backend honors it only with ALLOW_DEV_IDENTITY_HEADER=1 (backend/app/deps.py). Fictional data only.
const DEV_PERSON_ID = process.env.NEXT_PUBLIC_DEV_PERSON_ID ?? "";

export function identityHeaders(): Record<string, string> {
  return DEV_PERSON_ID ? { "X-Person-Id": DEV_PERSON_ID } : {};
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
