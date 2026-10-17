// Report detail (artboard "Report"). Ticket: CIA-11.
// Every value shows its verbatim quote and whether code verified it (AGENTS.md §3).
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Route } from "next";
import { CheckIcon, ChevronRightIcon, CirclePlayIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { getReport } from "@/lib/api";
import { CHECKLIST_LABEL, dayTime, duration, firstName } from "@/lib/format";
import { cn } from "@/lib/utils";

export default async function ReportPage(props: PageProps<"/patients/[id]/reports/[reportId]">) {
  const { id, reportId } = await props.params;
  const report = await getReport(id, reportId);
  if (!report) notFound();

  // Mentioned items first, then the ones nobody talked about.
  const items = [...report.items].sort((a, b) => Number(a.value === null) - Number(b.value === null));

  return (
    <AppShell>
      <TopBar
        back={`/patients/${id}`}
        title={dayTime(report.created_at)}
        subtitle={`${report.caregiver.display_name} · versión ${report.version}`}
      />
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        {/* Playback is wired in CIA-13 together with the segment format (CIA-23). */}
        <Button size="xl" className="h-14 justify-start rounded-2xl text-left">
          <CirclePlayIcon className="size-7!" />
          <span className="flex flex-col">
            <span>Escuchar nota de voz</span>
            <span className="text-[13px] font-normal opacity-90">
              {report.audio_duration_sec ? `${duration(report.audio_duration_sec)} · ` : ""}audio original
            </span>
          </span>
        </Button>

        <p className="text-[13px] text-muted-foreground">Cada dato muestra lo que se dijo, palabra por palabra.</p>

        <ItemGroup aria-label="Temas del reporte" className="gap-0 overflow-hidden rounded-xl border bg-card">
          {items.map((it, i) => {
            const label = CHECKLIST_LABEL[it.item];
            const unverified = it.value !== null && !it.quote_verified;
            return (
              <div key={it.item}>
                {i > 0 && <ItemSeparator className="my-0" />}
                <Item className={cn("rounded-none px-4 py-3.5", unverified && "bg-warning-tint")}>
                  <ItemContent>
                    <span className="text-[13px] font-bold tracking-wide text-muted-foreground uppercase">{label}</span>
                    {it.value !== null && <ItemTitle className="text-base font-bold">{it.value}</ItemTitle>}
                    {it.value !== null && !unverified && (
                      <ItemDescription className="line-clamp-none text-sm italic">“{it.quote}”</ItemDescription>
                    )}
                    {unverified && (
                      <ItemDescription className="line-clamp-none text-sm text-warning-foreground">
                        La cita no aparece en la transcripción. No se usa para alertas.
                      </ItemDescription>
                    )}
                  </ItemContent>
                  <ItemActions className="self-start">
                    {it.value === null ? (
                      <Badge variant="missing" size="lg">
                        No mencionado
                      </Badge>
                    ) : unverified ? (
                      <Badge variant="warning">Sin verificar</Badge>
                    ) : (
                      <Badge variant="success">
                        <CheckIcon />
                        verificada
                      </Badge>
                    )}
                  </ItemActions>
                </Item>
              </div>
            );
          })}
        </ItemGroup>

        {report.alerts.length > 0 && (
          <Item asChild className="min-h-11 rounded-2xl bg-warning px-4 py-3.5 font-bold text-warning-foreground">
            <Link href={`/patients/${id}/alerts` as Route}>
              <ItemContent>
                {report.alerts.length} {report.alerts.length === 1 ? "alerta" : "alertas"} en este reporte
              </ItemContent>
              <ChevronRightIcon className="size-5" />
            </Link>
          </Item>
        )}

        <p className="text-[13px] text-muted-foreground">
          Las correcciones se mandan por WhatsApp a {firstName(report.caregiver.display_name)} y crean una versión nueva. Las
          anteriores quedan visibles.
        </p>
      </main>
    </AppShell>
  );
}
