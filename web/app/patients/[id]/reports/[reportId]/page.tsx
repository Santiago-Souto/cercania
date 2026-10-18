// Report detail (artboard "Report"). Ticket: CIA-11.
// Every value shows its verbatim quote and whether code verified it (AGENTS.md §3).
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Route } from "next";
import { ChevronRightIcon } from "lucide-react";
import { AudioPlayer, ClipIcon, PlayClipButton, PlayerBar } from "@/components/app/audio-player";
import { ReportItemRow } from "@/components/app/report-item-row";
import { AppShell, TopBar } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Item, ItemContent, ItemGroup } from "@/components/ui/item";
import { getReport } from "@/lib/api";
import { dayTime, duration, firstName } from "@/lib/format";

export default async function ReportPage(props: PageProps<"/patients/[id]/reports/[reportId]">) {
  const { id, reportId } = await props.params;
  const report = await getReport(id, reportId);
  if (!report) notFound();

  // Mentioned items first, then the ones nobody talked about.
  const items = [...report.items].sort((a, b) => Number(a.value === null) - Number(b.value === null));
  const when = dayTime(report.created_at);

  return (
    <AppShell>
      <TopBar
        back={`/patients/${id}`}
        title={dayTime(report.created_at)}
        subtitle={`${report.caregiver.display_name} · versión ${report.version}`}
      />
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <AudioPlayer audioPaths={[report.audio_url]}>
        {report.audio_url ? (
          <>
            <Button asChild size="xl" className="h-14 justify-start rounded-2xl text-left">
              <PlayClipButton clip={{ key: "note", audioPath: report.audio_url, start: 0, end: null, label: when }}>
                <span className="flex size-7 items-center justify-center rounded-full border-2 border-current">
                  <ClipIcon clipKey="note" className="size-3.5" />
                </span>
                <span className="flex flex-col">
                  <span>Escuchar nota de voz</span>
                  <span className="text-[13px] font-normal opacity-90">
                    {report.audio_duration_sec ? `${duration(report.audio_duration_sec)} · ` : ""}audio original
                  </span>
                </span>
              </PlayClipButton>
            </Button>
            <PlayerBar />
          </>
        ) : (
          <p className="rounded-2xl border bg-card px-4 py-3 text-[13px] text-muted-foreground">
            Este reporte no tiene nota de voz guardada (se escribió, o el audio no se pudo guardar).
          </p>
        )}

        <p className="text-[13px] text-muted-foreground">Cada dato muestra lo que se dijo, palabra por palabra.</p>

        <ItemGroup aria-label="Temas del reporte" className="gap-0 overflow-hidden rounded-xl border bg-card">
          {items.map((it, i) => (
            <ReportItemRow key={it.item} item={it} audioPath={report.audio_url} when={when} first={i === 0} />
          ))}
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
        </AudioPlayer>
      </main>
    </AppShell>
  );
}
