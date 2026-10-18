// Family read-only view (artboard "Family"). Ticket: CIA-12.
import Link from "next/link";
import type { Route } from "next";
import { MessageCircleIcon } from "lucide-react";
import { AppShell, Brand } from "@/components/app/shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmergencyCallButton } from "@/components/app/emergency-call";
import { getPatient, getReports } from "@/lib/api";
import { CHECKLIST_LABEL, dayTime, firstName } from "@/lib/format";

export default async function FamilyPage(props: PageProps<"/patients/[id]/family">) {
  const { id } = await props.params;
  const [patient, reports] = await Promise.all([getPatient(id), getReports(id)]);
  const last = reports[0];
  const flagged = reports.filter((r) => r.red_flag);
  const notes = reports.flatMap((r) => r.alerts.filter((a) => a.type !== "missing_item"));

  return (
    <AppShell>
      <header className="flex items-center justify-between px-5 pt-5 pb-3">
        <Brand />
        <Badge variant="neutral" size="lg">
          Familia · solo lectura
        </Badge>
      </header>
      <main className="flex flex-1 flex-col gap-4 px-4 pb-5">
        <section className="flex flex-col gap-1 px-1">
          <h1 className="text-[28px] leading-tight font-bold">{patient.display_name}</h1>
          {last && (
            <p className="text-[15px] text-muted-foreground">
              Último turno: {dayTime(last.created_at).toLowerCase()}, reportado por {firstName(last.caregiver.display_name)}
            </p>
          )}
        </section>

        {flagged.map((r) => (
          <Alert key={r.id} variant="danger-soft">
            <AlertTitle className="font-bold">{dayTime(r.created_at)}: se reportó una señal de alarma</AlertTitle>
            <AlertDescription className="text-sm">El equipo fue avisado. Ante cualquier duda, contactá a la residencia.</AlertDescription>
            <EmergencyCallButton contact={patient.emergency_contact} className="mt-2" />
          </Alert>
        ))}

        {last && (
          <Card className="text-base">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Cómo estuvo</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[15px]">
                {last.items.map((it) => (
                  <div key={it.item} className="flex flex-col">
                    <dt className="text-[13px] text-muted-foreground">{CHECKLIST_LABEL[it.item]}</dt>
                    <dd className={it.value !== null && it.quote_verified ? "font-bold" : "text-muted-foreground"}>
                      {it.value !== null && it.quote_verified ? it.value : "No consta"}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
        )}

        {notes.length > 0 && (
          <Card className="text-base">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Para tener en cuenta</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex list-disc flex-col gap-2 pl-5 marker:text-warning-foreground">
                {notes.map((a, i) => (
                  <li key={i}>{a.detail}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        <Button asChild size="xl" variant="outline-primary">
          <Link href={`/patients/${id}/messages` as Route}>
            <MessageCircleIcon />
            Escribir al equipo de salud
          </Link>
        </Button>

        <p className="text-[13px] text-muted-foreground">
          Esto es un registro de lo que reportó el equipo de cuidado. No es un diagnóstico ni reemplaza la historia clínica.
        </p>
      </main>
    </AppShell>
  );
}
