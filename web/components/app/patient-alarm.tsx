// Patient "Necesito ayuda" and red-flag "cómo me siento" messages, as the team sees them (AGENTS.md §7).
// Shown on the patient home (newest of the last 24 h) and on Alertas (all). The emergency line is fixed text.
import Link from "next/link";
import type { Route } from "next";
import { ChevronRightIcon, HandHelpingIcon, TriangleAlertIcon } from "lucide-react";
import { EmergencyCallButton } from "@/components/app/emergency-call";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, getPatientMessages } from "@/lib/api";
import { dayTime, firstName } from "@/lib/format";
import type { EmergencyContact, PatientMessage } from "@/lib/types";

export const isAlarm = (m: PatientMessage) => m.kind === "help" || m.red_flag;

/** Every patient message, newest first. Family has no `read_patient_messages` (403): nothing to show. */
export async function getPatientMessagesOrNone(patientId: string): Promise<PatientMessage[]> {
  try {
    return await getPatientMessages(patientId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) return [];
    throw err;
  }
}

/** Help requests and red flags, newest first. */
export async function getPatientAlarms(patientId: string): Promise<PatientMessage[]> {
  return (await getPatientMessagesOrNone(patientId)).filter(isAlarm);
}

export function isRecent(m: PatientMessage, hours = 24): boolean {
  return Date.now() - new Date(m.created_at).getTime() < hours * 3600_000;
}

export function PatientAlarmCard({
  m,
  patientName,
  contact,
  alertsHref,
  more = 0,
}: {
  m: PatientMessage;
  patientName: string;
  contact: EmergencyContact | null | undefined;
  /** Set on the home: links to Alertas, where every alarm is listed. */
  alertsHref?: string;
  /** Other alarms not shown in this card. */
  more?: number;
}) {
  const help = m.kind === "help";
  const name = firstName(patientName);
  const seen = m.seen_by.map((s) => firstName(s.name)).filter(Boolean);
  return (
    <Card
      role="alert"
      className="gap-3 border-2 border-danger bg-danger-soft text-base text-danger-soft-foreground shadow-[0_6px_20px_-8px_var(--danger)] ring-0"
    >
      <CardHeader className="flex items-center gap-3">
        <span className="relative flex size-11 shrink-0 items-center justify-center">
          <span className="absolute inset-0 rounded-full bg-danger/40 motion-safe:animate-ping" aria-hidden />
          <span className="relative flex size-11 items-center justify-center rounded-full bg-danger text-danger-foreground">
            {help ? <HandHelpingIcon className="size-5" /> : <TriangleAlertIcon className="size-5" />}
          </span>
        </span>
        <div className="flex min-w-0 flex-col">
          <CardTitle className="font-heading text-xl leading-tight font-bold">
            {help ? `${name} pidió ayuda` : `Posible emergencia de ${name}`}
          </CardTitle>
          <span className="text-[14px]">{dayTime(m.created_at)}</span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-[15px]">
        {help ? (
          <p>Tocó “Necesito ayuda” en su pantalla.</p>
        ) : (
          <p className="rounded-lg bg-card px-3 py-2 text-foreground italic">“{m.text}”</p>
        )}
        {m.reason && <p>Motivo: {m.reason}</p>}
        <p className="font-bold">Contactá a emergencias o al médico.</p>
        {seen.length > 0 && <p className="text-[13px]">Lo vio: {seen.join(", ")}</p>}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2 border-0 bg-transparent pt-0">
        <EmergencyCallButton contact={contact} />
        {alertsHref && (
          <Button asChild variant="link" size="touch" className="px-0 font-bold text-danger-soft-foreground">
            <Link href={alertsHref as Route}>
              {more > 0 ? `Ver ${more + 1} alertas` : "Ver en alertas"}
              <ChevronRightIcon />
            </Link>
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
