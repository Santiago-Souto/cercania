// Copy for "Mis pacientes" that fits who is looking (CIA-57). Pure functions, shared by the server page.
import type { Me, MyPatient, Role } from "@/lib/types";

export type EmptyCopy = { title: string; description: string };

const HEALTH_TEAM = new Set<Role>(["doctor", "nurse", "institution"]);

/** Empty list: the message depends on what the person can do, not a generic "no patients". */
export function emptyCopy(me: Me): EmptyCopy {
  if (me.can_add_patients) {
    return {
      title: "Todavía no tenés pacientes asignados",
      description: "Agregá un paciente, invitalo a registrarse con su celular, o esperá a que una persona administradora te asigne uno.",
    };
  }
  if (me.is_admin) {
    return {
      title: "No tenés pacientes a tu cargo",
      description: "Como persona administradora asignás roles desde “Usuarios y roles”. Si también acompañás a un paciente, podés asignarte un rol ahí.",
    };
  }
  return {
    title: "Todavía no tenés un rol asignado",
    description: "Si alguien te invitó, la invitación aparece acá cuando entrás con ese número. Si no, una persona administradora te asigna un rol.",
  };
}

/** One line under the list that matches the viewer's roles; null when there is nothing useful to add. */
export function listNote(patients: MyPatient[]): string | null {
  if (patients.length === 0) return null;
  const roles = new Set(patients.map((p) => p.role));
  if (roles.has("caregiver")) return "Tocá un paciente para ver su último turno o mandar un reporte nuevo.";
  if ([...roles].some((r) => HEALTH_TEAM.has(r))) return "Ves los pacientes que te asignaron: sus reportes, alertas y la pregunta con citas.";
  if (roles.has("family")) return "Ves el resumen y las alertas de tu familiar. Para hablar con el equipo de salud, entrá al paciente.";
  return null;
}
