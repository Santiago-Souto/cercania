"use client";
// Browser-side calls (polling, form submits). Server components use lib/api.ts.
// Same-origin through the /api rewrite, so the session cookie goes along; a 401 sends the browser to /login.

import { BROWSER_API, onUnauthorized } from "./api-shared";
import type { AppNotification, ChecklistItem, Me, Message, MyInvite, Report } from "./types";

export class ClientApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

/** `quiet`: a 401 is just an error, no redirect to /login. For chrome around the page (the account
 * bar), which also renders during logged-out screens and transitions (CIA-61). */
async function call<T>(path: string, init?: RequestInit & { quiet?: boolean }): Promise<T> {
  const { quiet = false, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`${BROWSER_API}${path}`, {
      ...rest,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...rest.headers },
    });
  } catch {
    throw new ClientApiError("network", "No pudimos conectar con el servidor. Probá de nuevo.");
  }
  if (res.status === 401) {
    if (!quiet) onUnauthorized();
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

/** GET /me: who is logged in and their roles (memberships). Never redirects: logged out, it just fails. */
export function fetchMe() {
  return call<Me>(`/me`, { quiet: true });
}

export function fetchNotifications(opts: { since?: string; unreadOnly?: boolean }) {
  const q = new URLSearchParams({ limit: "50" });
  if (opts.since) q.set("since", opts.since);
  if (opts.unreadOnly) q.set("unread_only", "1");
  return call<{ notifications: AppNotification[]; unread_count: number }>(`/me/notifications?${q}`);
}

/** Pending invites to the caller's phone, polled so an invite shows up while the app is open. */
export function fetchMyInvites() {
  return call<{ invites: MyInvite[] }>(`/me/invites`);
}

export function markNotificationRead(id: string) {
  return call<AppNotification>(`/me/notifications/${id}/read`, { method: "POST" });
}

export function fetchMessages(patientId: string) {
  return call<{ messages: Message[] }>(`/patients/${patientId}/messages`).then((d) => d.messages);
}

/** `clientId` is reused on retry, so a send that timed out after the server stored it is not duplicated. */
export function sendMessage(patientId: string, text: string, clientId: string) {
  return call<Message>(`/patients/${patientId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, client_id: clientId }),
  });
}

/** Signed URL for a report's voice note. `audioPath` is the report's `audio_url` (GET /reports/{id}/audio). */
export function fetchAudioUrl(audioPath: string) {
  return call<{ url: string; expires_in_sec: number }>(audioPath);
}

/** Caregiver correction: only the changed items. An empty value means "not mentioned". Creates a new version. */
export function correctReport(reportId: string, corrections: { item: ChecklistItem; value: string }[]) {
  return call<Report>(`/reports/${reportId}/corrections`, {
    method: "POST",
    body: JSON.stringify({ corrections }),
  });
}
