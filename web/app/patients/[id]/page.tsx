// Patient home (artboard "Main"). Ticket: CIA-11.
import Link from "next/link";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { ChevronLeftIcon, MessageCircleIcon, MicIcon, TriangleAlertIcon, UsersIcon } from "lucide-react";
import { AppShell, Brand, BottomNav } from "@/components/app/shell";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { EmergencyCallButton } from "@/components/app/emergency-call";
import { EmergencyContactCard } from "@/components/app/emergency-contact-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { Progress } from "@/components/ui/progress";
import { getMyPatients, getPatient, getReports } from "@/lib/api";
import { CHECKLIST_LABEL, dayTime, duration, firstName } from "@/lib/format";

export default async function PatientHome(props: PageProps<"/patients/[id]">) {
  const { id } = await props.params;
  // The patient never sees reports or alerts about them (the backend answers 403): send them to their view first.
  const mine = await getMyPatients();
  const role = mine.find((p) => p.id === id)?.role;
  if (role === "patient") redirect(`/patients/${id}/me` as Route);
  const [patient, reports] = await Promise.all([getPatient(id), getReports(id)]);
  const healthTeam = role === "doctor" || role === "nurse" || role === "institution";
  const last = reports[0];
  const plan = patient.care_plan;
  const covered = last ? last.items.filter((i) => i.value !== null).length : 0;
  const total = last ? last.items.length : 0;
  const pct = total ? Math.round((covered / total) * 100) : 0;

  // `care_plan` is null when the patient has no active plan (e.g. a patient who signed up on their own).
  const planRows: [string, string][] = plan
    ? [
        ...plan.medications.map((m): [string, string] => [m.name, m.times.join(" · ")]),
        ["Indicaciones", plan.indications.join(" · ") || "Ninguna"],
        ["Alergias", plan.allergies.join(" · ") || "Ninguna registrada"],
      ]
    : [["Plan de cuidado", "Sin plan registrado"]];

  return (
    <AppShell>
      <header className="flex items-center justify-between px-5 pt-5 pb-3">
        <Brand />
        <Button asChild variant="link" size="touch" className="font-bold">
          <Link href="/patients">
            <ChevronLeftIcon />
            Mis pacientes
          </Link>
        </Button>
      </header>

      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        <Button asChild size="xl">
          <Link href={`/patients/${id}/reports/new` as Route}>
            <MicIcon />
            Nuevo reporte
          </Link>
        </Button>

        {last?.red_flag && (
          <Alert variant="danger">
            <TriangleAlertIcon />
            <AlertTitle className="font-heading text-lg font-bold">Señal de alarma en el último reporte</AlertTitle>
            <AlertDescription className="flex flex-col gap-2 text-[15px]">
              <strong>Contactá a emergencias o al médico.</strong>
              <EmergencyCallButton contact={patient.emergency_contact} className="self-start" />
            </AlertDescription>
          </Alert>
        )}

        {healthTeam && (
          <Button asChild size="xl" variant="outline-primary">
            <Link href={`/patients/${id}/messages` as Route}>
              <MessageCircleIcon />
              Mensajes de la familia
            </Link>
          </Button>
        )}

        <Card className="text-base">
          <CardHeader className="flex items-center gap-3">
            <Avatar className="size-12">
              <AvatarFallback className="bg-secondary font-heading text-xl font-bold text-primary">
                {patient.display_name[0]}
              </AvatarFallback>
            </Avatar>
            <div>
              <CardTitle className="text-2xl font-bold">{patient.display_name}</CardTitle>
              <CardDescription>{patient.location ? `${patient.location} · ` : ""}Plan de cuidado</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {planRows.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{k}</span>
                <span className="text-right font-bold">{v}</span>
              </div>
            ))}
            <Button asChild variant="outline" size="touch" className="mt-2 w-full font-bold">
              <Link href={`/patients/${id}/team` as Route}>
                <UsersIcon />
                Equipo y accesos
              </Link>
            </Button>
          </CardContent>
        </Card>

        <EmergencyContactCard patientId={id} contact={patient.emergency_contact} canEdit={role === "caregiver" || role === "doctor"} />

        {last && (
          <section className="flex flex-col gap-2.5">
            <h2 className="text-lg font-semibold">Último turno</h2>
            <Link href={`/patients/${id}/reports/${last.id}` as Route} className="rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
              <Card className="gap-3 px-4 text-base transition-colors hover:bg-accent">
                <div className="flex items-baseline justify-between">
                  <span className="font-bold">
                    {dayTime(last.created_at)} · {firstName(last.caregiver.display_name)}
                  </span>
                  <span className="text-[13px] text-muted-foreground">versión {last.version}</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between text-sm">
                    <span>
                      {covered} de {total} temas registrados
                    </span>
                    <span className="text-muted-foreground">{pct}%</span>
                  </div>
                  <Progress value={pct} aria-label="Temas registrados" />
                </div>
                <div className="flex flex-wrap gap-2">
                  {last.missing_items.map((m) => (
                    <Badge key={m} variant="missing" size="lg">
                      Faltó: {CHECKLIST_LABEL[m].toLowerCase()}
                    </Badge>
                  ))}
                  {last.alerts.length > 0 && (
                    <Badge variant="warning" size="lg">
                      {last.alerts.length} {last.alerts.length === 1 ? "alerta" : "alertas"}
                    </Badge>
                  )}
                </div>
              </Card>
            </Link>
          </section>
        )}

        <section className="flex flex-col gap-2.5">
          <h2 className="text-lg font-semibold">Reportes</h2>
          <ItemGroup className="gap-0 rounded-xl border bg-card">
            {reports.map((r, i) => (
              <div key={r.id}>
                {i > 0 && <ItemSeparator className="my-0" />}
                <Item asChild className="min-h-11 rounded-none px-4 py-3.5">
                  <Link href={(r.red_flag ? `/patients/${id}/alerts` : `/patients/${id}/reports/${r.id}`) as Route}>
                    <ItemContent>
                      <ItemTitle className="text-base font-bold">{dayTime(r.created_at)}</ItemTitle>
                      <ItemDescription className="text-[13px]">
                        {r.caregiver.display_name}
                        {r.audio_duration_sec ? ` · nota de voz ${duration(r.audio_duration_sec)}` : ""}
                      </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                      {r.red_flag ? (
                        <Badge variant="danger" size="lg">
                          Señal de alarma
                        </Badge>
                      ) : r.alerts.length > 0 ? (
                        <Badge variant="warning" size="lg">
                          {r.alerts.length} {r.alerts.length === 1 ? "alerta" : "alertas"}
                        </Badge>
                      ) : (
                        <Badge variant="success" size="lg">
                          Sin alertas
                        </Badge>
                      )}
                    </ItemActions>
                  </Link>
                </Item>
              </div>
            ))}
          </ItemGroup>
        </section>
      </main>

      <BottomNav patientId={id} active="home" />
    </AppShell>
  );
}
