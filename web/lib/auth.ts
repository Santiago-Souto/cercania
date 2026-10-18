"use client";
// Browser side of sign-up / login (CIA-32): POST /auth/* through the same-origin /api rewrite, so the
// session cookie set by /auth/verify lands on the web origin. Nothing here says whether a phone has an
// account (AGENTS.md section 6): the backend answers the same way, and so do these messages.

import { ApiError, BROWSER_API, errorFrom, NETWORK_ERROR_MESSAGE } from "./api-shared";
import type { CodeSent, Verified } from "./types";

export { landingFor, safeNext } from "./landing";

/** What the code screen needs, kept in sessionStorage (never in the URL: the phone is personal data). */
export type PendingLogin = {
  mode: "signup" | "login";
  phone: string;
  name?: string;
  email?: string;
  next?: string;
  sent: CodeSent;
  sentAt: number;
};

const PENDING_KEY = "cercania:pending-login";

export function savePending(p: PendingLogin) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(p));
  } catch {
    // storage blocked: the code screen sends the person back to /login
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

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BROWSER_API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("network_error", NETWORK_ERROR_MESSAGE, 0);
  }
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

/** Sends a code: sign-up carries name and email, login only the phone. */
export function requestCode(p: Pick<PendingLogin, "mode" | "phone" | "name" | "email">): Promise<CodeSent> {
  return p.mode === "signup"
    ? post<CodeSent>("/auth/signup", { name: p.name, email: p.email || null, phone: p.phone })
    : post<CodeSent>("/auth/login", { phone: p.phone });
}

export function verifyCode(phone: string, code: string): Promise<Verified> {
  return post<Verified>("/auth/verify", { phone, code });
}

export async function logout(): Promise<void> {
  await post("/auth/logout", {}).catch(() => {});
}

/** Spanish message per error code in docs/contract.md "Auth"; the backend message otherwise. */
export function authErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return NETWORK_ERROR_MESSAGE;
  switch (err.code) {
    case "code_invalid":
      return "El código no es correcto. Revisalo y probá de nuevo.";
    case "code_expired":
      return "El código venció. Pedí uno nuevo.";
    case "too_many_attempts":
      return "Demasiados intentos con este código. Pedí uno nuevo.";
    case "sms_unreachable":
      return "No pudimos mandar el SMS a ese número. Revisalo y probá de nuevo en un minuto.";
    case "invalid_request":
      return "Revisá los datos: el código tiene 6 números y el nombre no puede quedar vacío.";
    default:
      return err.message;
  }
}

/** Errors after which this code can no longer work: show the "código vencido" state. */
export function isDeadCode(err: unknown): boolean {
  return err instanceof ApiError && (err.code === "code_expired" || err.code === "too_many_attempts");
}
