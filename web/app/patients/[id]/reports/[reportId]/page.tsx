// Report detail (artboard "Report"). Ticket: CIA-11.
// Every value shows its verbatim quote and whether code verified it (AGENTS.md §3).
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Route } from "next";
import { ChevronRightIcon } from "lucide-react";
import { AudioPlayer, ClipIcon, PlayClipButton, PlayerBar } from "@/components/app/audio-player";
import { ReportItemRow } from "@/components/app/report-item-row";
import { AppShell, TopBar } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { getMe, getReport, getReportVersions } from "@/lib/api";
import { dayTime, duration } from "@/lib/format";
import { CorrectionForm } from "./correction-form";

export default async function ReportPage(props: PageProps<"/patients/[id]/reports/[reportId]">) {
  const { id, reportId } = await props.params;
  const { v } = await props.searchParams;
  const report = await getReport(id, reportId);
  if (!report) notFound();
  const [versions, me] = await Promise.all([getReportVersions(reportId), getMe()]);

  // `?v=N` shows an older version, read-only. No param (or the latest) is the current version.
  const wanted = Number(Array.isArray(v) ? v[0] : v);
  const shown = versions.find((x) => x.version === wanted && x.version !== report.version);
  const canCorrect =
    !shown &&
    report.kind !== "emergency" &&
    me.memberships.some((m) => m.patient_id === id && m.role === "caregiver");
  const shownAlerts = shown?.alerts ?? report.alerts;

  // Mentioned items first, then the ones nobody talked about.
  const items = [...(shown?.items ?? report.items)].sort((a, b) => Number(a.value === null) - Number(b.value === null));
  const when = dayTime(report.created_at);

  return (
    <AppShell>
      <TopBar
        back={`/patients/${id}`}
        title={dayTime(report.created_at)}
        subtitle={`${report.caregiver.display_name} · versión ${shown?.version ?? report.version}`}
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

        {shown && (
          <Item asChild className="min-h-11 rounded-2xl bg-warning px-4 py-3.5 text-warning-foreground">
            <Link href={`/patients/${id}/reports/${reportId}` as Route} replace>
              <ItemContent>
                Versión {shown.version}, solo lectura. Ver la versión actual ({report.version})
              </ItemContent>
              <ChevronRightIcon className="size-5" />
            </Link>
          </Item>
        )}

        <p className="text-[13px] text-muted-foreground">Cada dato muestra lo que se dijo, palabra por palabra.</p>

        <ItemGroup aria-label="Temas del reporte" className="gap-0 overflow-hidden rounded-xl border bg-card">
          {items.map((it, i) => (
            <ReportItemRow key={it.item} item={it} audioPath={report.audio_url} when={when} first={i === 0} />
          ))}
        </ItemGroup>

        {shownAlerts.length > 0 && (
          <Item asChild className="min-h-11 rounded-2xl bg-warning px-4 py-3.5 font-bold text-warning-foreground">
            <Link href={`/patients/${id}/alerts` as Route}>
              <ItemContent>
                {shownAlerts.length} {shownAlerts.length === 1 ? "alerta" : "alertas"} en este reporte
              </ItemContent>
              <ChevronRightIcon className="size-5" />
            </Link>
          </Item>
        )}

        {canCorrect && <CorrectionForm key={report.version} reportId={reportId} items={report.items} />}

        <section aria-labelledby="versions-title" className="flex flex-col gap-2">
          <h2 id="versions-title" className="text-[13px] font-bold tracking-wide text-muted-foreground uppercase">
            Versiones
          </h2>
          <ItemGroup className="gap-0 overflow-hidden rounded-xl border bg-card">
            {[...versions].reverse().map((ver, i) => {
              const latest = ver.version === report.version;
              const current = shown ? ver.version === shown.version : latest;
              return (
                <div key={ver.version}>
                  {i > 0 && <ItemSeparator className="my-0" />}
                  <Item asChild className="min-h-11 rounded-none px-4 py-3">
                    <Link
                      href={(latest ? `/patients/${id}/reports/${reportId}` : `?v=${ver.version}`) as Route}
                      replace
                      aria-current={current ? "true" : undefined}
                    >
                      <ItemContent>
                        <ItemTitle className="font-bold">
                          Versión {ver.version}
                          {latest && " · actual"}
                        </ItemTitle>
                        <ItemDescription>
                          {ver.created_by.display_name} · {dayTime(ver.created_at)}
                        </ItemDescription>
                      </ItemContent>
                      {ver.source === "correction" && <Badge variant="neutral">Corregido</Badge>}
                      {current && <Badge variant="outline">Viendo</Badge>}
                    </Link>
                  </Item>
                </div>
              );
            })}
          </ItemGroup>
        </section>

        <p className="text-[13px] text-muted-foreground">
          Cada corrección crea una versión nueva. Las anteriores quedan visibles.
        </p>
        </AudioPlayer>
      </main>
    </AppShell>
  );
}
