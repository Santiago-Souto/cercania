// Single entry point for data. Screens never fetch directly.
// NEXT_PUBLIC_USE_FAKE_DATA=1 -> contract-shaped fake data (SIMULATED, see lib/fake.ts). Opt-in only:
// a deploy that forgets the variable must hit the real API and fail loudly, never show fabricated patients.
// Otherwise -> the backend at NEXT_PUBLIC_API_URL (CIA-14 finishes this switch, incl. session cookies).

import { connection } from "next/server";
import * as fake from "./fake";
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

export const USE_FAKE = process.env.NEXT_PUBLIC_USE_FAKE_DATA === "1";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "unknown",
      body?.error?.message ?? "No pudimos conectar con el servidor. Probá de nuevo.",
      res.status,
    );
  }
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
