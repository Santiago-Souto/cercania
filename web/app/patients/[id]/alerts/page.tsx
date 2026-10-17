// Alerts (artboard "Alerts"). Ticket: CIA-12.
// Red flags use a fixed message (AGENTS.md §7). Alerts come from code, never from the model.
import Link from "next/link";
import type { Route } from "next";
import { BellOffIcon, CircleAlertIcon, TrendingDownIcon, TriangleAlertIcon } from "lucide-react";
import { AppShell, BottomNav, ScreenHeader } from "@/components/app/shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemContent, ItemMedia, ItemTitle } from "@/components/ui/item";
import { getPatient, getReports } from "@/lib/api";
import { CHECKLIST_LABEL, dayTime, firstName } from "@/lib/format";
import type { Alert as AlertT } from "@/lib/types";

const GROUPS: { type: AlertT["type"]; label: string }[] = [
  { type: "omission", label: "Omisión · plan de cuidado" },
  { type: "change", label: "Cambio · respecto a lo habitual" },
];

export default async function AlertsPage(props: PageProps<"/patients/[id]/alerts">) {
  const { id } = await props.params;
  const [patient, reports] = await Promise.all([getPatient(id), getReports(id)]);
  const flagged = reports.filter((r) => r.red_flag);
  const last = reports[0];
  const alerts = reports.flatMap((r) => r.alerts.map((a) => ({ a, r })));
  const nothing = flagged.length === 0 && alerts.length === 0 && (!last || last.missing_items.length === 0);

  return (
    <AppShell>
      <ScreenHeader title="Alertas" subtitle={`${patient.display_name} · últimos reportes`} />
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        {flagged.map((r) => (
          <Alert key={r.id} variant="danger">
            <TriangleAlertIcon />
            <AlertTitle className="font-heading text-lg font-bold">Señal de alarma</AlertTitle>
            <AlertDescription className="flex flex-col gap-1 text-[15px]">
              <span>
                {dayTime(r.created_at)} · {firstName(r.caregiver.display_name)} dijo: <em>“{r.red_flag_quote}”</em>
              </span>
              <strong>Contactá a emergencias o al médico.</strong>
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
                        {type === "change" ? <TrendingDownIcon className="size-4" /> : <CircleAlertIcon className="size-4" />}
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
            <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">Temas faltantes</h2>
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
                  El bot le pregunta a {firstName(last.caregiver.display_name)} por WhatsApp.
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
