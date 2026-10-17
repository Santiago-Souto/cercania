// Ask with cited answers (artboard "Ask"). Ticket: CIA-13.
// Works without JS: the composer is a GET form, the answer renders on the server.
import Link from "next/link";
import type { Route } from "next";
import { ArrowRightIcon, PlayIcon } from "lucide-react";
import { AppShell, BottomNav, ScreenHeader } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from "@/components/ui/item";
import { getPatient, getReports, queryPatient } from "@/lib/api";
import { dayTime, duration, firstName } from "@/lib/format";

const SUGGESTIONS = ["¿Cómo viene comiendo?", "¿Durmió bien anoche?", "¿Tomó la de las 20:00?"];

export default async function AskPage(props: PageProps<"/patients/[id]/ask">) {
  const { id } = await props.params;
  const { q } = await props.searchParams;
  const question = typeof q === "string" ? q.trim() : "";
  const [patient, reports] = await Promise.all([getPatient(id), getReports(id)]);
  const result = question ? await queryPatient(id, question) : null;
  const byId = new Map(reports.map((r) => [r.id, r]));

  return (
    <AppShell>
      <ScreenHeader title="Preguntar" subtitle={`Sobre ${patient.display_name}. Cada respuesta cita el reporte.`} />
      <main className="flex flex-1 flex-col gap-3.5 px-4 pb-4">
        {result && (
          <>
            <Bubble align="end">
              <BubbleContent className="text-base">{question}</BubbleContent>
            </Bubble>
            <Bubble variant="outline" className="max-w-full" aria-live="polite">
              <BubbleContent className="flex flex-col gap-3 bg-card p-4 text-base">
                {result.confidence === "answered" ? (
                  <Badge variant="success">Respondido con citas</Badge>
                ) : (
                  <Badge variant="missing">No consta en los reportes</Badge>
                )}
                <p className="text-[17px]">{result.answer}</p>
                {result.note && <p className="text-[13px] text-muted-foreground">{result.note}</p>}
                <ItemGroup className="gap-2">
                  {result.citations.map((c, i) => {
                    const r = byId.get(c.report_id);
                    return (
                      // Seeking to audio_start_sec is wired in CIA-13.
                      <Item key={i} asChild variant="muted" className="min-h-11 items-start rounded-xl border">
                        <button type="button">
                          <ItemMedia className="size-9 rounded-full bg-primary text-primary-foreground">
                            <PlayIcon className="size-4 fill-current" />
                          </ItemMedia>
                          <ItemContent>
                            <ItemTitle className="text-sm font-normal italic">“{c.quote}”</ItemTitle>
                            <ItemDescription className="text-[13px]">
                              {r ? `${dayTime(r.created_at)} · ${firstName(r.caregiver.display_name)} · ` : ""}
                              {duration(c.audio_start_sec)}–{duration(c.audio_end_sec)}
                            </ItemDescription>
                          </ItemContent>
                        </button>
                      </Item>
                    );
                  })}
                </ItemGroup>
              </BubbleContent>
            </Bubble>
          </>
        )}

        <p className="text-[13px] text-muted-foreground">
          Si los reportes no lo dicen, la respuesta es “No consta en los reportes”. Nunca se adivina.
        </p>

        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((sug) => (
            <Button key={sug} asChild variant="outline" size="touch">
              <Link href={`/patients/${id}/ask?q=${encodeURIComponent(sug)}` as Route}>{sug}</Link>
            </Button>
          ))}
        </div>
      </main>

      <form method="get" className="sticky bottom-[73px] border-t bg-card px-3 py-2.5">
        <InputGroup className="h-11 rounded-full bg-background">
          <InputGroupInput
            name="q"
            aria-label="Tu pregunta"
            placeholder="Escribí tu pregunta…"
            defaultValue={question}
            required
            className="text-base"
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton type="submit" variant="default" size="icon-sm" className="rounded-full" aria-label="Enviar pregunta">
              <ArrowRightIcon />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </form>
      <BottomNav patientId={id} active="ask" />
    </AppShell>
  );
}
