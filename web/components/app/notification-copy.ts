// Who gets notified, from their roles (CIA-59). Mirrors the backend (backend/app/models.py):
// a reported emergency goes to caregivers and family (`emergency_recipients`); a patient's
// "Necesito ayuda" or red-flag message goes to caregivers and the health team (`patient_team`).
// A patient, or an admin without patients, is never notified, so they are never asked.
import type { Me, Role } from "@/lib/types";

const HEALTH_TEAM: Role[] = ["doctor", "nurse", "institution"];

/** Neutral text when the role could not be read: never "tus pacientes" to someone who may have none. */
export const GENERIC_NOTIFICATION_TEXT =
  "Te avisamos en este dispositivo cuando haya una emergencia, mientras tengas CercanIA abierta.";

/** Text of the opt-in for this person, or null when they never receive notifications. */
export function notificationText(me: Pick<Me, "memberships">): string | null {
  const roles = new Set(me.memberships.map((m) => m.role));
  const end = ", mientras tengas CercanIA abierta.";
  if (roles.has("caregiver")) {
    return `Te avisamos en este dispositivo cuando haya una emergencia o un pedido de ayuda de tus pacientes${end}`;
  }
  const health = HEALTH_TEAM.some((r) => roles.has(r));
  const family = roles.has("family");
  if (health && family) {
    return `Te avisamos en este dispositivo cuando un paciente que acompañás pida ayuda o tenga una emergencia${end}`;
  }
  if (health) return `Te avisamos en este dispositivo cuando uno de tus pacientes pida ayuda o mande un mensaje que puede ser una emergencia${end}`;
  if (family) return `Te avisamos en este dispositivo cuando se reporte una emergencia de tu familiar${end}`;
  return null; // patient only, admin only, or no roles: nothing will ever arrive
}
