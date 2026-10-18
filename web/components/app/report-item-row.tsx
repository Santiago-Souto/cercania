// One checklist item of a report: label, recorded value, level, details, verbatim quote and whether code
// verified it (AGENTS.md §3). Shared by the report detail (CIA-11) and the screen after sending (CIA-46).
import { CheckIcon } from "lucide-react";
import { ClipIcon, PlayClipButton } from "@/components/app/audio-player";
import { Badge } from "@/components/ui/badge";
import { Item, ItemActions, ItemContent, ItemDescription, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { CHECKLIST_LABEL, levelLabel } from "@/lib/format";
import type { ReportItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** `audioPath`: what the player plays (API path or local blob URL); null when there is no audio. */
export function ReportItemRow({
  item: it,
  audioPath,
  when,
  first,
}: {
  item: ReportItem;
  audioPath: string | null;
  when: string;
  first: boolean;
}) {
  const label = CHECKLIST_LABEL[it.item];
  const mentioned = it.value !== null;
  // A correction is typed by a caregiver and has no quote (quote_verified null): not "unverified".
  const corrected = mentioned && it.source === "correction";
  const unverified = mentioned && !corrected && it.quote_verified !== true;
  const doses = it.details?.doses ?? [];
  return (
    <div>
      {!first && <ItemSeparator className="my-0" />}
      <Item className={cn("rounded-none px-4 py-3.5", unverified && "bg-warning-tint")}>
        <ItemContent>
          <span className="text-[13px] font-bold tracking-wide text-muted-foreground uppercase">{label}</span>
          {mentioned && <ItemTitle className="text-base font-bold">{it.value}</ItemTitle>}
          {mentioned && (it.level || doses.length > 0) && (
            <div className="flex flex-wrap items-center gap-1.5">
              {it.level && <Badge variant="neutral">Nivel: {levelLabel(it.level)}</Badge>}
              {doses.map((d) => (
                <Badge key={`${d.plan_ref}-${d.time}`} variant={d.quote_verified === false ? "warning" : "outline"}>
                  {d.time} · {d.given === true ? "dada" : d.given === false ? "no dada" : "sin aclarar"}
                  {d.quote_verified === false && " · sin verificar"}
                </Badge>
              ))}
            </div>
          )}
          {mentioned && it.quote && !unverified && audioPath && it.audio_start_sec != null ? (
            // Tapping the quote plays exactly that fragment of the voice note.
            <PlayClipButton
              clip={{
                key: it.item,
                audioPath,
                start: it.audio_start_sec,
                end: it.audio_end_sec ?? null,
                label: `${label.toLowerCase()} · ${when}`,
              }}
              className="-mx-1 flex min-h-11 items-center gap-2 rounded-lg px-1 text-left text-sm text-muted-foreground italic hover:bg-muted"
            >
              <ClipIcon clipKey={it.item} className="size-3.5 shrink-0 text-primary" />
              <span>“{it.quote}”</span>
            </PlayClipButton>
          ) : (
            mentioned && it.quote && <ItemDescription className="line-clamp-none text-sm italic">“{it.quote}”</ItemDescription>
          )}
          {unverified && (
            // Shown, never hidden. An unverified quote is not used for alerts.
            <ItemDescription className="line-clamp-none text-sm text-warning-foreground">
              Esta cita no aparece en la transcripción. No se usa para alertas.
            </ItemDescription>
          )}
        </ItemContent>
        <ItemActions className="self-start">
          {!mentioned ? (
            <Badge variant="missing" size="lg">
              No mencionado
            </Badge>
          ) : corrected ? (
            <Badge variant="neutral">Corregido</Badge>
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
}
