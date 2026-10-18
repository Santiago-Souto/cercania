// Single entry point for data. Screens never fetch directly.
// NEXT_PUBLIC_USE_FAKE_DATA=1 -> contract-shaped fake data (SIMULATED, see lib/fake.ts). Opt-in only:
// a deploy that forgets the variable must hit the real API and fail loudly, never show fabricated patients.
// Otherwise -> the backend at NEXT_PUBLIC_API_URL (CIA-14 finishes this switch, incl. session cookies).

import { cookies } from "next/headers";
import { connection } from "next/server";
import { API_URL, ApiError, errorFrom, identityHeaders, USE_FAKE } from "./api-shared";
import * as fake from "./fake";
import { DEFAULT_PERSONA_ID, PERSONA_COOKIE } from "./persona";
import type {
  Invite,
  Member,
  Message,
  MyPatient,
  NewPatient,
  Patient,
  PatientMessage,
  QueryResponse,
  Report,
  Role,
} from "./types";

export { ApiError, USE_FAKE };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const personId = (await cookies()).get(PERSONA_COOKIE)?.value ?? DEFAULT_PERSONA_ID;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    // SIMULATED persona (cookie) wins over NEXT_PUBLIC_DEV_PERSON_ID: see lib/persona.ts.
    headers: { "Content-Type": "application/json", ...identityHeaders(), "X-Person-Id": personId, ...init?.headers },
  });
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

// Fake-data mode only reads fixtures; writing to the real API from it would mix real rows with fake screens.
const FAKE_WRITE = () => new ApiError("fake_mode", "Con datos de prueba ficticios no se puede guardar. Usá la app con el servidor real.", 409);

export async function createPatient(body: NewPatient): Promise<Patient> {
  if (USE_FAKE) throw FAKE_WRITE();
  return request<Patient>(`/patients`, { method: "POST", body: JSON.stringify(body) });
}

export async function createInvite(patientId: string, contact: string, role: Role): Promise<Invite> {
  if (USE_FAKE) throw FAKE_WRITE();
  return request<Invite>(`/patients/${patientId}/invites`, {
    method: "POST",
    body: JSON.stringify({ contact, role }),
  });
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
