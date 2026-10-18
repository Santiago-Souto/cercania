// Browser-side calls that send text or a recording: new report (CIA-31) and patient messages (CIA-35).
// Kept apart from lib/api.ts because that file uses server-only APIs.

import { API_URL, ApiError, errorFrom, identityHeaders, NETWORK_ERROR_MESSAGE, USE_FAKE } from "./api-shared";
import { fakeProcessResult } from "./fake";
import type { PatientMessageResult, ProcessResult } from "./types";

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

/** POSTs `{...fields, text}` as JSON, or `fields` + `audio` as multipart, to an endpoint that takes either. */
async function postTextOrAudio<T>(path: string, fields: Record<string, string>, input: ReportInput): Promise<T> {
  let body: BodyInit;
  const headers: Record<string, string> = identityHeaders();
  if ("text" in input) {
    body = JSON.stringify({ ...fields, text: input.text });
    headers["Content-Type"] = "application/json";
  } else {
    // Multipart: the browser sets Content-Type with the boundary. Drop codec params ("audio/webm;codecs=opus").
    const type = input.audio.type.split(";")[0] || "audio/webm";
    const form = new FormData();
    for (const [k, v] of Object.entries(fields)) form.append(k, v);
    form.append("audio", new File([input.audio], audioFilename(type), { type }));
    body = form;
  }
  return post<T>(path, body, headers);
}

async function post<T>(path: string, body: BodyInit, headers: Record<string, string>): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      body,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError("network_error", NETWORK_ERROR_MESSAGE, 0);
  }
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

export async function sendReport(patientId: string, clientId: string, input: ReportInput): Promise<ProcessResult> {
  if (USE_FAKE) {
    await new Promise((r) => setTimeout(r, 800));
    return fakeProcessResult;
  }
  return postTextOrAudio<ProcessResult>(`/patients/${patientId}/reports`, { client_id: clientId }, input);
}

/** Patient view (CIA-35): POST /patients/{id}/patient-messages. "help" never carries text and never reaches the model. */
export async function sendPatientMessage(
  patientId: string,
  input: { kind: "help" } | ({ kind: "feeling" } & ReportInput),
): Promise<PatientMessageResult> {
  const path = `/patients/${patientId}/patient-messages`;
  if (input.kind === "help") {
    return post<PatientMessageResult>(path, JSON.stringify({ kind: "help" }), {
      ...identityHeaders(),
      "Content-Type": "application/json",
    });
  }
  return postTextOrAudio<PatientMessageResult>(path, { kind: "feeling" }, input);
}
