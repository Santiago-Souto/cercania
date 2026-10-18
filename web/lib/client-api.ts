"use client";
// Browser-side calls (polling, form submits). Server components use lib/api.ts.
// Logged in: the session cookie identifies the caller (same-origin /api proxy). Otherwise SIMULATED X-Person-Id
// from the persona cookie (lib/persona.ts).

import { BROWSER_API_URL, identityHeaders, isLoggedIn } from "./api-shared";
import { DEFAULT_PERSONA_ID, PERSONA_COOKIE } from "./persona";
import type { AppNotification } from "./types";

/** Key for per-person browser state (seen notifications). "session" when logged in for real. */
export function currentPersonId(): string {
  if (isLoggedIn()) return "session";
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${PERSONA_COOKIE}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : DEFAULT_PERSONA_ID;
}

/** Switch the simulated identity and do a full load, so server data and the notification poller restart as the new person. */
export function switchPerson(id: string) {
  document.cookie = `${PERSONA_COOKIE}=${encodeURIComponent(id)}; path=/; max-age=31536000; samesite=lax`;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = "/patients";
}

export class ClientApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BROWSER_API_URL}${path}`, {
      ...init,
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...identityHeaders(), ...init?.headers },
    });
  } catch {
    throw new ClientApiError("network", "No pudimos conectar con el servidor. Probá de nuevo.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ClientApiError(
      body?.error?.code ?? "unknown",
      body?.error?.message ?? "No pudimos conectar con el servidor. Probá de nuevo.",
    );
  }
  return res.json() as Promise<T>;
}

export function fetchNotifications(opts: { since?: string; unreadOnly?: boolean }) {
  const q = new URLSearchParams({ limit: "50" });
  if (opts.since) q.set("since", opts.since);
  if (opts.unreadOnly) q.set("unread_only", "1");
  return call<{ notifications: AppNotification[]; unread_count: number }>(`/me/notifications?${q}`);
}

export function markNotificationRead(id: string) {
  return call<AppNotification>(`/me/notifications/${id}/read`, { method: "POST" });
}
