"use client";
// Browser-side calls (polling, form submits). Server components use lib/api.ts.
// Same-origin through the /api rewrite, so the session cookie goes along; a 401 sends the browser to /login.

import { BROWSER_API, onUnauthorized } from "./api-shared";
import type { AppNotification } from "./types";

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
    res = await fetch(`${BROWSER_API}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ClientApiError("network", "No pudimos conectar con el servidor. Probá de nuevo.");
  }
  if (res.status === 401) {
    onUnauthorized();
    throw new ClientApiError("unauthenticated", "Iniciá sesión para continuar.");
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

/** Signed URL for a report's voice note. `audioPath` is the report's `audio_url` (GET /reports/{id}/audio). */
export function fetchAudioUrl(audioPath: string) {
  return call<{ url: string; expires_in_sec: number }>(audioPath);
}
