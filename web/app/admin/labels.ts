// Shared by the admin page (server) and its forms (client). Not a "use client" module, so the server
// page gets the real object: values imported from a client module are only references there.
import { ROLE_LABEL } from "@/lib/format";
import type { AdminMembership, AdminRole } from "@/lib/types";

export const ADMIN_ROLE_LABEL: Record<AdminRole, string> = { ...ROLE_LABEL, admin: "Administración" };

/** A membership as the admin reads it: role + whose. The `patient` role means the person *is* the
 *  patient on that profile (their own, e.g. from self sign-up), so it never reads "paciente de <name>":
 *  it names the profile only when it differs from the person's name. */
export function membershipLabel(m: AdminMembership, personName: string): { role: string; detail: string; text: string } {
  const role = ADMIN_ROLE_LABEL[m.role];
  if (m.role !== "patient") return { role, detail: `de ${m.patient_name}`, text: `${role.toLowerCase()} de ${m.patient_name}` };
  const detail = m.patient_name === personName ? "" : `(perfil ${m.patient_name})`;
  return { role, detail, text: [role.toLowerCase(), detail].filter(Boolean).join(" ") };
}
