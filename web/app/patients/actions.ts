"use server";
// Server actions for add patient + team (CIA-34). They call the backend through lib/api.ts, so the
// caller's identity travels the same way as every server read; the backend checks permissions.

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { ApiError, createInvite, createPatient } from "@/lib/api";
import { checkPhone } from "@/lib/team";
import type { NewPatient, Role } from "@/lib/types";

export type ActionError = { code: string; message: string };

const NETWORK: ActionError = { code: "network", message: "No pudimos conectar con el servidor. Probá de nuevo." };

/** Backend errors become a value the form can show; anything else (redirects included) is rethrown. */
function asError(e: unknown): ActionError {
  if (e instanceof ApiError) return { code: e.code, message: e.message };
  if (e instanceof TypeError) return NETWORK; // fetch could not reach the API
  throw e;
}

export type CreatePatientResult =
  | { error: ActionError }
  | { patientId: string; inviteErrors: { contact: string; error: ActionError }[] };

/** POST /patients, then one POST /invites per queued invite. Redirects to the patient when all went through. */
export async function createPatientAction(
  body: NewPatient,
  invites: { contact: string; role: Role }[],
): Promise<CreatePatientResult> {
  let patientId: string;
  try {
    patientId = (await createPatient(body)).id;
  } catch (e) {
    return { error: asError(e) };
  }
  const inviteErrors: { contact: string; error: ActionError }[] = [];
  for (const inv of invites) {
    try {
      await createInvite(patientId, inv.contact, inv.role);
    } catch (e) {
      inviteErrors.push({ contact: inv.contact, error: asError(e) });
    }
  }
  revalidatePath("/patients");
  if (inviteErrors.length) return { patientId, inviteErrors };
  redirect(`/patients/${patientId}`);
}

/** POST /patients/{id}/invites from the team page. */
export async function inviteAction(patientId: string, contact: string, role: Role): Promise<{ error: ActionError } | { ok: true }> {
  const checked = checkPhone(contact);
  if ("error" in checked) return { error: { code: "phone_invalid", message: checked.error } };
  try {
    await createInvite(patientId, checked.phone, role);
  } catch (e) {
    return { error: asError(e) };
  }
  revalidatePath(`/patients/${patientId}/team`);
  return { ok: true };
}
