// Report detail (artboard "Report"). Ticket: CIA-11.
// Every value shows its verbatim quote and whether code verified it (AGENTS.md §3).
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Route } from "next";
import { CheckIcon, ChevronRightIcon } from "lucide-react";
import { AudioPlayer, ClipIcon, PlayClipButton, PlayerBar } from "@/components/app/audio-player";
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
                    {it.value !== null && !unverified && report.audio_url && it.audio_start_sec != null && it.audio_end_sec != null ? (
                      // Tapping the quote plays exactly that fragment of the voice note.
                      <PlayClipButton
                        clip={{
                          key: it.item,
                          audioPath: report.audio_url,
                          start: it.audio_start_sec,
                          end: it.audio_end_sec,
                          label: `${label.toLowerCase()} · ${when}`,
                        }}
                        className="-mx-1 flex min-h-11 items-center gap-2 rounded-lg px-1 text-left text-sm text-muted-foreground italic hover:bg-muted"
                      >
                        <ClipIcon clipKey={it.item} className="size-3.5 shrink-0 text-primary" />
                        <span>“{it.quote}”</span>
                      </PlayClipButton>
                    ) : (
                      it.value !== null &&
                      !unverified && <ItemDescription className="line-clamp-none text-sm italic">“{it.quote}”</ItemDescription>
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
        </AudioPlayer>
      </main>
    </AppShell>
  );
}
