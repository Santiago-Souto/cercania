// Single entry point for data in server components. Screens never fetch directly.
// Calls the backend at NEXT_PUBLIC_API_URL as the logged-in person: the browser's session cookie does
// not travel with a server-side fetch, so request() forwards it. No session or a 401 -> /login.

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { API_URL, ApiError, errorFrom, SESSION_COOKIE } from "./api-shared";
import type {
  AdminPeople,
  AdminPerson,
  AdminRole,
  Invite,
  Me,
  Member,
  Membership,
  Message,
  MyInvite,
  EmergencyContact,
  MyPatient,
  NewPatient,
  Patient,
  PatientMessage,
  QueryResponse,
  Report,
  ReportVersion,
  Role,
} from "./types";

export { ApiError };

/** Set by proxy.ts on app screens: the page being rendered, so the login can come back to it. */
const PATH_HEADER = "x-cercania-path";

async function toLogin(): Promise<never> {
  const next = (await headers()).get(PATH_HEADER);
  redirect(next ? `/login?mode=login&next=${encodeURIComponent(next)}` : "/login?mode=login");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return toLogin();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Cookie: `${SESSION_COOKIE}=${session}`,
      ...init?.headers,
    },
  });
  if (res.status === 401) return toLogin();
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

export async function getReportVersions(reportId: string): Promise<ReportVersion[]> {
  await connection(); // patient data is always live: render at request time
  const data = await request<{ versions: ReportVersion[] }>(`/reports/${reportId}/versions`);
  return data.versions;
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

export async function setEmergencyContact(patientId: string, contact: EmergencyContact | null): Promise<Patient> {
  return request<Patient>(`/patients/${patientId}/emergency-contact`, { method: "PATCH", body: JSON.stringify(contact) });
}

/** DELETE /patients/{id}: a caregiver archives the patient (records stay stored, nobody keeps access). */
export async function archivePatient(patientId: string): Promise<void> {
  await request(`/patients/${patientId}`, { method: "DELETE" });
}

/** POST /invites (CIA-48): a caregiver invites a patient who has no profile yet. */
export async function invitePatientWithoutProfile(contact: string): Promise<Invite> {
  return request<Invite>(`/invites`, { method: "POST", body: JSON.stringify({ contact, role: "patient" }) });
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

/** A team member listing messages marks them seen: pass `limit` when only a few are shown. */
export async function getPatientMessages(patientId: string, limit?: number): Promise<PatientMessage[]> {
  await connection(); // patient data is always live: render at request time
  const query = limit ? `?limit=${limit}` : "";
  const data = await request<{ messages: PatientMessage[] }>(`/patients/${patientId}/patient-messages${query}`);
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

// --- Admin (CIA-48, CIA-58): roles only, never links to patients ---

export async function getAdminPeople(): Promise<AdminPeople> {
  await connection();
  return request<AdminPeople>(`/admin/people`);
}

export async function adminSetRole(personId: string, role: Role, confirm: boolean): Promise<AdminPerson> {
  return request<AdminPerson>(`/admin/people/${personId}/role`, {
    method: "PUT",
    body: JSON.stringify({ role, confirm_overwrite: confirm }),
  });
}

export async function adminMakeAdmin(personId: string, confirm: boolean): Promise<AdminPerson> {
  return request<AdminPerson>(`/admin/people/${personId}/admin`, {
    method: "PUT",
    body: JSON.stringify({ confirm_overwrite: confirm }),
  });
}

export async function adminPreRegister(phone: string, role: AdminRole, confirm: boolean): Promise<unknown> {
  return request(`/admin/pre-registrations`, {
    method: "POST",
    body: JSON.stringify({ phone, role, confirm_overwrite: confirm }),
  });
}

export async function adminDeletePreRegistration(id: string): Promise<unknown> {
  return request(`/admin/pre-registrations/${id}`, { method: "DELETE" });
}
