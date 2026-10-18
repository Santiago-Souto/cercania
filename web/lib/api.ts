// Single entry point for data in server components. Screens never fetch directly.
// Calls the backend at NEXT_PUBLIC_API_URL as the logged-in person: the browser's session cookie does
// not travel with a server-side fetch, so request() forwards it. No session or a 401 -> /login.

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { API_URL, ApiError, errorFrom, SESSION_COOKIE } from "./api-shared";
import type {
  Invite,
  Me,
  Member,
  Membership,
  Message,
  MyInvite,
  MyPatient,
  NewPatient,
  Patient,
  PatientMessage,
  QueryResponse,
  Report,
  Role,
} from "./types";

export { ApiError };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) redirect("/login?mode=login");
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Cookie: `${SESSION_COOKIE}=${session}`,
      ...init?.headers,
    },
  });
  if (res.status === 401) redirect("/login?mode=login");
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

export async function getPatient(id: string): Promise<Patient> {
  await connection(); // patient data is always live: render at request time
  return request<Patient>(`/patients/${id}`);
}

export async function getReports(patientId: string): Promise<Report[]> {
  await connection(); // patient data is always live: render at request time
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
  return request<QueryResponse>(`/patients/${patientId}/query`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function getMyPatients(): Promise<MyPatient[]> {
  await connection(); // patient data is always live: render at request time
  const data = await request<{ patients: MyPatient[] }>(`/me/patients`);
  return data.patients;
}

export async function getMembers(patientId: string): Promise<{ members: Member[]; invites: Invite[] }> {
  await connection(); // patient data is always live: render at request time
  return request(`/patients/${patientId}/members`);
}

export async function createPatient(body: NewPatient): Promise<Patient> {
  return request<Patient>(`/patients`, { method: "POST", body: JSON.stringify(body) });
}

export async function createInvite(patientId: string, contact: string, role: Role): Promise<Invite> {
  return request<Invite>(`/patients/${patientId}/invites`, {
    method: "POST",
    body: JSON.stringify({ contact, role }),
  });
}

/** Invites to the caller's own phone, shown on "Mis pacientes" to accept or decline. */
export async function getMyInvites(): Promise<MyInvite[]> {
  await connection(); // always live: render at request time
  const data = await request<{ invites: MyInvite[] }>(`/me/invites`);
  return data.invites;
}

export async function acceptInvite(inviteId: string): Promise<Membership> {
  return request<Membership>(`/me/invites/${inviteId}/accept`, { method: "POST" });
}

export async function declineInvite(inviteId: string): Promise<void> {
  await request(`/me/invites/${inviteId}/decline`, { method: "POST" });
}

export async function getPatientMessages(patientId: string): Promise<PatientMessage[]> {
  await connection(); // patient data is always live: render at request time
  const data = await request<{ messages: PatientMessage[] }>(`/patients/${patientId}/patient-messages`);
  return data.messages;
}

export async function getMessages(patientId: string): Promise<Message[]> {
  await connection(); // patient data is always live: render at request time
  const data = await request<{ messages: Message[] }>(`/patients/${patientId}/messages`);
  return data.messages;
}

export async function getMe(): Promise<Me> {
  await connection(); // the logged-in person is per request
  return request<Me>(`/me`);
}

/** The logged-in person, or null when this device has no valid session. Never redirects, so the login
 *  page can use it to skip the form; a backend that cannot be reached also counts as "no session". */
export async function getSession(): Promise<Me | null> {
  await connection();
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return null;
  try {
    const res = await fetch(`${API_URL}/me`, { cache: "no-store", headers: { Cookie: `${SESSION_COOKIE}=${session}` } });
    return res.ok ? ((await res.json()) as Me) : null;
  } catch {
    return null;
  }
}
