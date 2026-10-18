// Alerts (artboard "Alerts"). Ticket: CIA-12.
// Red flags use a fixed message (AGENTS.md §7). Alerts come from code, never from the model.
// Patient "Necesito ayuda" and red-flag "cómo me siento" messages are listed here too, so "Ver" on
// their notification lands somewhere (they are patient messages, not reports).
import Link from "next/link";
import type { Route } from "next";
import { BellOffIcon, CircleAlertIcon, ListChecksIcon, TrendingDownIcon, TriangleAlertIcon } from "lucide-react";
import { EmergencyCallButton } from "@/components/app/emergency-call";
import { PatientAlarmCard, getPatientAlarms } from "@/components/app/patient-alarm";
import { AppShell, BottomNav, ScreenHeader } from "@/components/app/shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemContent, ItemMedia, ItemTitle } from "@/components/ui/item";
import { getPatient, getReports } from "@/lib/api";
import { CHECKLIST_LABEL, ROLE_LABEL, dayTime, firstName } from "@/lib/format";
import type { Alert as AlertT, AlertNotification } from "@/lib/types";

const RECIPIENT_LABEL: Record<AlertNotification["to"], string> = {
  caregiver: ROLE_LABEL.caregiver,
  family: ROLE_LABEL.family,
};

function deliveryStatus(n: AlertNotification): { label: string; variant: "success" | "missing" | "danger" } {
  if (n.status === "sent") return { label: "Enviado", variant: "success" };
  // "skipped" only appears on old rows; it means the channel was off, not that something broke.
  if (n.status === "skipped") return { label: "No activo", variant: "missing" };
  return { label: "No se pudo enviar", variant: "danger" };
}

const GROUPS: { type: AlertT["type"]; label: string }[] = [
  { type: "omission", label: "Omisión · plan de cuidado" },
  { type: "change", label: "Cambio · respecto a lo habitual" },
  { type: "missing_item", label: "Checklist incompleto" },
];

export default async function AlertsPage(props: PageProps<"/patients/[id]/alerts">) {
  const { id } = await props.params;
  const [patient, reports, alarms] = await Promise.all([getPatient(id), getReports(id), getPatientAlarms(id)]);
  const flagged = reports.filter((r) => r.red_flag);
  const emergencyOf = (r: (typeof reports)[number]) => r.alerts.find((a) => a.type === "emergency");
  const last = reports[0];
  const alerts = reports.flatMap((r) => r.alerts.map((a) => ({ a, r })));
  const nothing = alarms.length === 0 && flagged.length === 0 && alerts.length === 0 && (!last || last.missing_items.length === 0);

  return (
    <AppShell>
      <ScreenHeader title="Alertas" subtitle={`${patient.display_name} · últimos reportes`} />
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        {alarms.length > 0 && (
          <section className="flex flex-col gap-2.5" aria-label="Mensajes del paciente">
            {alarms.map((m) => (
              <PatientAlarmCard key={m.id} m={m} patientName={patient.display_name} contact={patient.emergency_contact} />
            ))}
          </section>
        )}

        {flagged.map((r) => (
          <Alert key={r.id} variant="danger">
            <TriangleAlertIcon />
            <AlertTitle className="font-heading text-lg font-bold">Señal de alarma</AlertTitle>
            <AlertDescription className="flex flex-col gap-1 text-[15px]">
              <span>
                {dayTime(r.created_at)} · {firstName(r.caregiver.display_name)} dijo: <em>“{r.red_flag_quote}”</em>
              </span>
              {r.triage?.reason && <span>Motivo: {r.triage.reason}</span>}
              {r.triage?.quote_verified === false && (
                <span className="text-[13px]">La cita no pudo verificarse en el reporte original.</span>
              )}
              <strong>Contactá a emergencias o al médico.</strong>
              <EmergencyCallButton contact={patient.emergency_contact} className="self-start" />
              {(emergencyOf(r)?.notifications?.length ?? 0) > 0 && (
                <ul className="mt-2 flex flex-col gap-1.5 rounded-lg bg-card p-3 text-card-foreground" aria-label="Avisos enviados">
                  {emergencyOf(r)!.notifications!.map((n, i) => {
                    const st = deliveryStatus(n);
                    return (
                      <li key={i} className="flex flex-col gap-0.5 text-[14px]">
                        <span className="flex items-center justify-between gap-2">
                          <span>
                            {RECIPIENT_LABEL[n.to]} · App
                          </span>
                          <Badge variant={st.variant}>{st.label}</Badge>
                        </span>
                        {n.status === "failed" && n.error && <span className="text-[12px]">{n.error}</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </AlertDescription>
          </Alert>
        ))}

        {GROUPS.map(({ type, label }) => {
          const group = alerts.filter(({ a }) => a.type === type);
          if (group.length === 0) return null;
          return (
            <section key={type} className="flex flex-col gap-2.5">
              <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">{label}</h2>
              {group.map(({ a, r }, i) => (
                <Card key={`${r.id}-${i}`} className="gap-2 text-base">
                  <CardContent>
                    <Item className="p-0">
                      <ItemMedia
                        className={
                          type === "change"
                            ? "size-7 rounded-full bg-secondary text-primary"
                            : "size-7 rounded-full bg-warning text-warning-foreground"
                        }
                      >
                        {type === "change" ? (
                          <TrendingDownIcon className="size-4" />
                        ) : type === "missing_item" ? (
                          <ListChecksIcon className="size-4" />
                        ) : (
                          <CircleAlertIcon className="size-4" />
                        )}
                      </ItemMedia>
                      <ItemContent>
                        <ItemTitle className="text-base font-bold">{a.detail}</ItemTitle>
                      </ItemContent>
                    </Item>
                  </CardContent>
                  <CardFooter className="border-0 bg-transparent pt-0">
                    <Button asChild variant="link" size="touch" className="px-0 font-bold">
                      <Link href={`/patients/${id}/reports/${r.id}` as Route}>Ver reporte de {dayTime(r.created_at).toLowerCase()}</Link>
                    </Button>
                  </CardFooter>
                </Card>
              ))}
            </section>
          );
        })}

        {last && last.missing_items.length > 0 && (
          <section className="flex flex-col gap-2.5">
            <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">Temas faltantes · último reporte</h2>
            <Card className="text-base">
              <CardContent className="flex flex-col gap-2.5">
                <CardDescription>El reporte de {dayTime(last.created_at).toLowerCase()} no habló de:</CardDescription>
                <div className="flex flex-wrap gap-2">
                  {last.missing_items.map((m) => (
                    <Badge key={m} variant="missing" size="lg">
                      {CHECKLIST_LABEL[m]}
                    </Badge>
                  ))}
                </div>
                <CardDescription className="text-[13px]">
                  Podés pedirle a {firstName(last.caregiver.display_name)} que mande otro reporte con esos temas.
                </CardDescription>
              </CardContent>
            </Card>
          </section>
        )}

        {nothing && (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BellOffIcon />
              </EmptyMedia>
              <EmptyTitle>No hay alertas</EmptyTitle>
              <EmptyDescription>Todo lo reportado coincide con el plan de cuidado.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </main>
      <BottomNav patientId={id} active="alerts" />
    </AppShell>
  );
}
