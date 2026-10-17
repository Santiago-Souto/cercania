// Family <-> health team messages (artboard "Messages"). Ticket: CIA-36 (bonus). Human-to-human, no model.
import { ArrowRightIcon, TriangleAlertIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Message, MessageContent, MessageFooter, MessageGroup } from "@/components/ui/message";
import { getMessages, getPatient } from "@/lib/api";
import { time } from "@/lib/format";

// Until auth lands (CIA-26/CIA-32) the viewer is the fictional family member.
const VIEWER_ID = "usr_005";

export default async function MessagesPage(props: PageProps<"/patients/[id]/messages">) {
  const { id } = await props.params;
  const [patient, messages] = await Promise.all([getPatient(id), getMessages(id)]);

  return (
    <AppShell>
      <TopBar back={`/patients/${id}/family`} title="Equipo de salud" subtitle={`Mensajes sobre ${patient.display_name}`} />
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <Alert variant="warning">
          <TriangleAlertIcon />
          <AlertDescription className="text-[13px]">No es para urgencias. Ante una urgencia, llamá a emergencias.</AlertDescription>
        </Alert>
        <MessageGroup className="gap-3">
          {messages.map((m) => {
            const mine = m.from.user_id === VIEWER_ID;
            return (
              <Message key={m.id} align={mine ? "end" : "start"}>
                <MessageContent className="gap-1">
                  <Bubble align={mine ? "end" : "start"} variant={mine ? "default" : "outline"}>
                    <BubbleContent className="text-base">{m.text}</BubbleContent>
                  </Bubble>
                  <MessageFooter>
                    {m.from.name} · {time(m.created_at)}
                  </MessageFooter>
                </MessageContent>
              </Message>
            );
          })}
        </MessageGroup>
      </main>
      {/* Sending lands in CIA-36. */}
      <form className="sticky bottom-0 border-t bg-card px-3 pt-2.5 pb-[calc(12px+env(safe-area-inset-bottom))]">
        <InputGroup className="h-11 rounded-full bg-background">
          <InputGroupInput aria-label="Mensaje" placeholder="Escribí un mensaje…" className="text-base" />
          <InputGroupAddon align="inline-end">
            <InputGroupButton type="submit" variant="default" size="icon-sm" className="rounded-full" aria-label="Enviar mensaje" disabled>
              <ArrowRightIcon />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </form>
    </AppShell>
  );
}
