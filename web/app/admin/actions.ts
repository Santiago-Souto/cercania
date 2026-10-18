"use server";
// Admin actions (CIA-48, CIA-58): list people and set their role (never links to patients). They call the backend through lib/api.ts with
// the admin's session; the backend checks `is_admin`. A change that would replace something comes back
// as `conflict` with the current state, and is sent again with `confirm` only after the admin agrees.

import { revalidatePath } from "next/cache";
import { adminDeletePreRegistration, adminMakeAdmin, adminPreRegister, adminSetRole, ApiError } from "@/lib/api";
import { checkPhone } from "@/lib/team";
import type { AdminRole, OverwriteCurrent, Role } from "@/lib/types";

export type AdminResult =
  | { ok: true }
  | { conflict: { message: string; current: OverwriteCurrent } }
  | { error: string };

function asResult(e: unknown): AdminResult {
  if (e instanceof ApiError) {
    if (e.code === "overwrite_required") return { conflict: { message: e.message, current: e.current as OverwriteCurrent } };
    return { error: e.message };
  }
  if (e instanceof TypeError) return { error: "No pudimos conectar con el servidor. Probá de nuevo." };
  throw e; // redirects (e.g. session expired) and real bugs
}

export async function setRoleAction(personId: string, role: Role, confirm = false): Promise<AdminResult> {
  try {
    await adminSetRole(personId, role, confirm);
  } catch (e) {
    return asResult(e);
  }
  revalidatePath("/admin");
  return { ok: true };
}

export async function makeAdminAction(personId: string, confirm = false): Promise<AdminResult> {
  try {
    await adminMakeAdmin(personId, confirm);
  } catch (e) {
    return asResult(e);
  }
  revalidatePath("/admin");
  return { ok: true };
}

export async function preRegisterAction(phone: string, role: AdminRole, confirm = false): Promise<AdminResult> {
  const checked = checkPhone(phone);
  if ("error" in checked) return { error: checked.error };
  try {
    await adminPreRegister(checked.phone, role, confirm);
  } catch (e) {
    return asResult(e);
  }
  revalidatePath("/admin");
  return { ok: true };
}

export async function deletePreRegistrationAction(id: string): Promise<AdminResult> {
  try {
    await adminDeletePreRegistration(id);
  } catch (e) {
    return asResult(e);
  }
  revalidatePath("/admin");
  return { ok: true };
}
