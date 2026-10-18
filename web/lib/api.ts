// Single entry point for data. Screens never fetch directly.
// NEXT_PUBLIC_USE_FAKE_DATA=1 -> contract-shaped fake data (SIMULATED, see lib/fake.ts). Opt-in only:
// a deploy that forgets the variable must hit the real API and fail loudly, never show fabricated patients.
// Otherwise -> the backend at NEXT_PUBLIC_API_URL, as the logged-in person (session cookie forwarded, CIA-32).

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { API_URL, ApiError, errorFrom, SESSION_COOKIE, USE_FAKE } from "./api-shared";
import * as fake from "./fake";
import { DEFAULT_PERSONA_ID, PERSONA_COOKIE } from "./persona";
import type {
  Invite,
  Member,
  Message,
  MyPatient,
  Patient,
  PatientMessage,
  QueryResponse,
  Report,
} from "./types";

export { ApiError, USE_FAKE };

/** Logged in: forward the session cookie. Otherwise the SIMULATED persona (lib/persona.ts) as X-Person-Id. */
async function identity(): Promise<Record<string, string>> {
  const jar = await cookies();
  const session = jar.get(SESSION_COOKIE)?.value;
  if (session) return { Cookie: `${SESSION_COOKIE}=${session}` };
  const personId = jar.get(PERSONA_COOKIE)?.value || process.env.NEXT_PUBLIC_DEV_PERSON_ID || DEFAULT_PERSONA_ID;
  return { "X-Person-Id": personId };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(await identity()), ...init?.headers },
  });
  if (res.status === 401) redirect("/login?mode=login&notice=expired"); // no session (or it expired): log in again
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

export async function getPatient(id: string): Promise<Patient> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return { ...fake.fakePatient, id };
  return request<Patient>(`/patients/${id}`);
}

export async function getReports(patientId: string): Promise<Report[]> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return fake.fakeReports;
  const data = await request<{ reports: Report[] }>(`/patients/${patientId}/reports`);
  return data.reports;
}

export async function getReport(patientId: string, reportId: string): Promise<Report | undefined> {
  await connection(); // patient data is always live: render at request time
  const reports = await getReports(patientId);
  return reports.find((r) => r.id === reportId);
}

export async function queryPatient(patientId: string, question: string): Promise<QueryResponse> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return fake.fakeQuery;
  return request<QueryResponse>(`/patients/${patientId}/query`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function getMyPatients(): Promise<MyPatient[]> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return fake.fakeMyPatients;
  const data = await request<{ patients: MyPatient[] }>(`/me/patients`);
  return data.patients;
}

export async function getMembers(patientId: string): Promise<{ members: Member[]; invites: Invite[] }> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return { members: fake.fakeMembers, invites: fake.fakeInvites };
  return request(`/patients/${patientId}/members`);
}

export async function getPatientMessages(patientId: string): Promise<PatientMessage[]> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return fake.fakePatientMessages;
  const data = await request<{ messages: PatientMessage[] }>(`/patients/${patientId}/patient-messages`);
  return data.messages;
}

export async function getMessages(patientId: string): Promise<Message[]> {
  await connection(); // patient data is always live: render at request time
  if (USE_FAKE) return fake.fakeMessages;
  const data = await request<{ messages: Message[] }>(`/patients/${patientId}/messages`);
  return data.messages;
}
