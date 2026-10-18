import type { ChecklistItem, Role } from "./types";

const TZ = "America/Montevideo";

export const CHECKLIST_LABEL: Record<ChecklistItem, string> = {
  appetite: "Apetito",
  sleep: "Sueño",
  urination: "Diuresis",
  medication: "Medicación",
  mood: "Ánimo",
  mobility: "Movilidad",
  pain: "Dolor",
  incidents: "Incidentes",
};

/** Spanish label for a coarse `level` code (docs/contract.md); unknown codes are shown as they come. */
const LEVEL_LABEL: Record<string, string> = {
  normal: "normal",
  low: "bajo",
  none: "ninguno",
  poor: "malo",
  agitated: "agitado",
  confused: "confundido",
  reduced: "reducida",
  present: "presente",
};
export const levelLabel = (level: string) => LEVEL_LABEL[level] ?? level;

export const ROLE_LABEL: Record<Role, string> = {
  caregiver: "Cuidador/a",
  family: "Familia",
  patient: "Paciente",
  doctor: "Médico/a",
  nurse: "Enfermería",
  institution: "Hospital o institución",
};

export function time(iso: string): string {
  return new Intl.DateTimeFormat("es-UY", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ }).format(
    new Date(iso),
  );
}

function dayKey(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d);
}

/** "Hoy", "Ayer" or a short date, in the residence's time zone. */
function day(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const today = dayKey(now);
  const yesterday = dayKey(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const key = dayKey(d);
  if (key === today) return "Hoy";
  if (key === yesterday) return "Ayer";
  return new Intl.DateTimeFormat("es-UY", { day: "numeric", month: "short", timeZone: TZ }).format(d);
}

export function dayTime(iso: string): string {
  return `${day(iso)} ${time(iso)}`;
}

export function duration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function firstName(name: string): string {
  return name.split(" ")[0];
}
