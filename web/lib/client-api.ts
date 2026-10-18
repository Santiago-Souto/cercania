"use client";
// Browser-side calls (polling, form submits). Server components use lib/api.ts.
// Same-origin through the /api rewrite, so the session cookie goes along; a 401 sends the browser to /login.

import { BROWSER_API, onUnauthorized } from "./api-shared";
import type { AppNotification, ChecklistItem, Message, Report } from "./types";

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

/** Opening a patient clears its "Novedades" dot (CIA-60). */
export function markPatientNotificationsRead(patientId: string) {
  return call<{ updated: number }>(`/me/notifications/read-all?patient_id=${encodeURIComponent(patientId)}`, {
    method: "POST",
  });
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
