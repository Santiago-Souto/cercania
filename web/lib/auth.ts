"use client";
// Browser side of the 6-digit SMS login (docs/contract.md "Auth"). Ticket: CIA-32.
// Calls go through the same-origin `/api` proxy (next.config.ts), so the HttpOnly session cookie the
// backend sets on POST /auth/verify lands on the web origin and server components can forward it.

import { ApiError, AUTH_FLAG_COOKIE, BROWSER_API_URL, errorFrom, NETWORK_ERROR_MESSAGE, USE_FAKE } from "./api-shared";
import { PERSONA_COOKIE } from "./persona";
import type { Role } from "./types";

export type CodeSent = { status: "code_sent"; phone_last4: string; expires_in_sec: number; resend_after_sec: number };
export type Membership = { patient_id: string; display_name: string; role: Role };
export type VerifyResult = { user: { id: string; name: string }; memberships: Membership[] };
export type SignupInput = { name: string; email?: string; phone: string };

/** Our own Spanish copy per contract error code, so the screen never depends on the backend's wording. */
const AUTH_ERRORS: Record<string, string> = {
  phone_invalid: "Revisá el número: tiene que incluir el código de país, por ejemplo +598 99 123 456.",
  too_many_requests: "Pediste un código hace poco. Esperá un minuto y probá de nuevo.",
  sms_unreachable: "No pudimos mandar el SMS a ese número. Revisalo y probá de nuevo en un minuto.",
  code_invalid: "El código no es correcto. Revisalo y probá de nuevo.",
  code_expired: "El código venció. Pedí uno nuevo.",
  too_many_attempts: "Demasiados intentos con este código. Pedí uno nuevo.",
  invalid_request: "Revisá los datos: el código tiene 6 números y el nombre no puede quedar vacío.",
  network_error: NETWORK_ERROR_MESSAGE,
};

export function authErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return AUTH_ERRORS[err.code] ?? err.message;
  return NETWORK_ERROR_MESSAGE;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BROWSER_API_URL}${path}`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("network_error", NETWORK_ERROR_MESSAGE, 0);
  }
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

// SIMULATED with fake data on (NEXT_PUBLIC_USE_FAKE_DATA=1): no backend, any 6 digits enter. See README "Simulated".
const fakeSent = (phone: string): CodeSent => ({
  status: "code_sent",
  phone_last4: phone.replace(/\D/g, "").slice(-4),
  expires_in_sec: 600,
  resend_after_sec: 60,
});

export function signup(input: SignupInput): Promise<CodeSent> {
  if (USE_FAKE) return Promise.resolve(fakeSent(input.phone));
  return post("/auth/signup", input);
}

export function login(phone: string): Promise<CodeSent> {
  if (USE_FAKE) return Promise.resolve(fakeSent(phone));
  return post("/auth/login", { phone });
}

export async function verify(phone: string, code: string): Promise<VerifyResult> {
  const result: VerifyResult = USE_FAKE
    ? { user: { id: "usr_fake", name: "Ana (ficticia)" }, memberships: [] }
    : await post("/auth/verify", { phone, code });
  setLoggedInFlag(true);
  return result;
}

export async function logout(): Promise<void> {
  try {
    if (!USE_FAKE) await post("/auth/logout");
  } finally {
    setLoggedInFlag(false);
  }
}

/** Where to land after verify: a single membership as `patient` goes to the patient view, anyone else to My patients. */
export function homeFor(memberships: Membership[]): string {
  if (memberships.length === 1 && memberships[0].role === "patient") return `/patients/${memberships[0].patient_id}/me`;
  return "/patients";
}

/**
 * Readable marker (not the session: that cookie is HttpOnly) telling browser code a real session exists,
 * so it stops sending the simulated X-Person-Id. The persona cookie is dropped for the same reason.
 */
function setLoggedInFlag(on: boolean) {
  document.cookie = on
    ? `${AUTH_FLAG_COOKIE}=1; path=/; max-age=${30 * 24 * 3600}; samesite=lax`
    : `${AUTH_FLAG_COOKIE}=; path=/; max-age=0; samesite=lax`;
  if (on) document.cookie = `${PERSONA_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

// The phone travels from /login to /login/code in sessionStorage, never in the URL.
const PENDING_KEY = "cercania_pending_login";

export type PendingLogin = {
  phone: string;
  phone_last4: string;
  /** Resend repeats sign-up for a new account: /auth/login sends nothing to a phone that is not registered yet. */
  signup?: SignupInput;
  expires_in_sec: number;
  /** Epoch ms when a new code may be requested (from resend_after_sec). */
  resend_at: number;
};

export function savePending(p: PendingLogin) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(p));
  } catch {
    // Private mode without storage: the code screen sends the user back to /login with a message.
  }
}

export function loadPending(): PendingLogin | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as PendingLogin) : null;
  } catch {
    return null;
  }
}

export function clearPending() {
  try {
    sessionStorage.removeItem(PENDING_KEY);
  } catch {
    // nothing to clear
  }
}
