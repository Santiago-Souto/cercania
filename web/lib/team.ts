// Add patient + team (CIA-34): rules shared by the form (browser) and the server actions.
// They mirror the backend checks (backend/app/schemas.py, api/auth.py normalize_phone) so most
// errors show next to the field before anything is sent.

import type { Role } from "./types";

/** Roles offered in the invite form. The health-team roles are left out of the form. */
export type InviteRole = Extract<Role, "caregiver" | "family" | "patient">;

/** What each role can do (AGENTS.md section 6), shown under the role select. */
export const ROLE_HELP: Record<InviteRole, string> = {
  caregiver: "Manda reportes, corrige, pregunta e invita a otras personas.",
  family: "Solo lectura: ve el resumen y las alertas.",
  patient: "Solo cuenta cómo se siente o pide ayuda. No ve reportes ni alertas.",
};

export const ROLES: InviteRole[] = ["caregiver", "family", "patient"];

const PHONE_RE = /^\+[1-9]\d{7,14}$/;

/** E.164 number or an error message (same rule as the backend's `phone_invalid`). */
export function checkPhone(raw: string): { phone: string } | { error: string } {
  const value = raw.trim();
  if (!value) return { error: "Escribí el número de celular." };
  if (value.includes("@")) return { error: "Invitá por número de celular, no por email: el email no se puede verificar." };
  const phone = value.replace(/[\s\-().]/g, "");
  if (!PHONE_RE.test(phone)) return { error: "Revisá el número: tiene que incluir el código de país, por ejemplo +598 99 123 456." };
  return { phone };
}

/** "8, 20:30" -> ["08:00", "20:30"], or an error message. Empty is allowed (no fixed time). */
export function parseTimes(raw: string): { times: string[] } | { error: string } {
  const parts = raw.split(/[,;\s]+/).filter(Boolean);
  const times: string[] = [];
  for (const p of parts) {
    const m = /^(\d{1,2})(?:[:.h](\d{2}))?$/.exec(p);
    const h = m ? Number(m[1]) : NaN;
    const min = m?.[2] ? Number(m[2]) : 0;
    if (!m || h > 23 || min > 59) return { error: `"${p}" no es un horario. Usá HH:MM, por ejemplo 08:00, 20:00.` };
    times.push(`${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`);
  }
  if (times.length > 12) return { error: "Hasta 12 horarios por medicación." };
  return { times };
}

export const MAX_TEXT = 120;
