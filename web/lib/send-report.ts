// Browser-side call for the new report screen (CIA-31): POST /patients/{id}/reports.
// Kept apart from lib/api.ts because that file uses server-only APIs. Same-origin through the /api rewrite.

import { ApiError, BROWSER_API, errorFrom, NETWORK_ERROR_MESSAGE, onUnauthorized } from "./api-shared";
import type { ProcessResult } from "./types";

export type ReportInput = { text: string } | { audio: Blob };

/** A fresh id per attempt. Re-sending with the same id returns the stored report instead of a new one. */
export function newClientId(): string {
  return `web_${crypto.randomUUID()}`;
}

/** File extension the backend accepts for a recorded MIME type (webm on Chrome/Firefox, mp4 on Safari). */
function audioFilename(type: string): string {
  if (type.startsWith("audio/mp4")) return "voice.m4a";
  if (type.startsWith("audio/ogg")) return "voice.ogg";
  return "voice.webm";
}

export async function sendReport(patientId: string, clientId: string, input: ReportInput): Promise<ProcessResult> {
  let body: BodyInit;
  const headers: Record<string, string> = {};
  if ("text" in input) {
    body = JSON.stringify({ client_id: clientId, text: input.text });
    headers["Content-Type"] = "application/json";
  } else {
    // Multipart: the browser sets Content-Type with the boundary. Drop codec params ("audio/webm;codecs=opus").
    const type = input.audio.type.split(";")[0] || "audio/webm";
    const form = new FormData();
    form.append("client_id", clientId);
    form.append("audio", new File([input.audio], audioFilename(type), { type }));
    body = form;
  }

  let res: Response;
  try {
    res = await fetch(`${BROWSER_API}/patients/${patientId}/reports`, {
      method: "POST",
      body,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError("network_error", NETWORK_ERROR_MESSAGE, 0);
  }
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<ProcessResult>;
}
