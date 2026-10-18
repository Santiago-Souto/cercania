"use client";
// Family <-> health team thread (CIA-36). Human-to-human: no model anywhere on this screen.
// Sends optimistically (sending -> sent / failed with retry) and polls every 5 s for replies.
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRightIcon, CircleAlertIcon, MessagesSquareIcon, RotateCwIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Message, MessageContent, MessageFooter, MessageGroup } from "@/components/ui/message";
import { Spinner } from "@/components/ui/spinner";
import { fetchMessages, sendMessage } from "@/lib/client-api";
import { dayTime, ROLE_LABEL } from "@/lib/format";
import type { Message as MessageT } from "@/lib/types";

const POLL_MS = 5000;
const MAX_CHARS = 2000;

// crypto.randomUUID only exists in secure contexts (HTTPS / localhost); a plain-HTTP demo URL must still send.
function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

type Pending = { key: string; text: string; status: "sending" | "failed"; error?: string };

export function MessageThread({ patientId, initial }: { patientId: string; initial: MessageT[] }) {
  const [messages, setMessages] = useState(initial);
  const [pending, setPending] = useState<Pending[]>([]);
  const [draft, setDraft] = useState("");
  const [pollError, setPollError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const count = messages.length + pending.length;

  // Follow new messages only while the reader is at the bottom; reading older ones is never interrupted.
  useEffect(() => {
    const onScroll = () => {
      stickToBottom.current = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 80;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // A poll that started before a newer poll, or before a send was acknowledged, is stale: applying it
  // would hide the just-sent message or bring back older read states. Each response carries the epoch
  // it started in and is dropped if anything newer has been applied since.
  const epoch = useRef(0);
  const applied = useRef(0);

  const refresh = useCallback(async () => {
    const started = ++epoch.current;
    try {
      const fresh = await fetchMessages(patientId);
      if (started < applied.current) return;
      applied.current = started;
      setMessages(fresh);
      setPollError(null);
    } catch (e) {
      setPollError(e instanceof Error ? e.message : "No pudimos actualizar los mensajes.");
    }
  }, [patientId]);

  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (stickToBottom.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [count]);

  async function deliver(p: Pending) {
    setPending((list) => [...list.filter((x) => x.key !== p.key), { ...p, status: "sending", error: undefined }]);
    try {
      const sent = await sendMessage(patientId, p.text, p.key);
      applied.current = ++epoch.current; // polls already in flight may predate this message
      setMessages((list) => (list.some((m) => m.id === sent.id) ? list : [...list, sent]));
      setPending((list) => list.filter((x) => x.key !== p.key));
    } catch (e) {
      const error = e instanceof Error ? e.message : "No pudimos enviar el mensaje.";
      setPending((list) => list.map((x) => (x.key === p.key ? { ...x, status: "failed", error } : x)));
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    stickToBottom.current = true; // your own message always scrolls into view
    void deliver({ key: newKey(), text, status: "sending" });
  }

  return (
    <>
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        {pollError && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertDescription>
              {pollError} Seguimos intentando.
            </AlertDescription>
          </Alert>
        )}
        {count === 0 ? (
          <Empty className="flex-1">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MessagesSquareIcon />
              </EmptyMedia>
              <EmptyTitle>Todavía no hay mensajes</EmptyTitle>
              <EmptyDescription>Escribí abajo para empezar la conversación entre la familia y el equipo de salud.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <MessageGroup className="gap-3" aria-live="polite">
            {messages.map((m) => (
              <Message key={m.id} align={m.mine ? "end" : "start"}>
                <MessageContent className="gap-1">
                  <Bubble align={m.mine ? "end" : "start"} variant={m.mine ? "default" : "outline"}>
                    <BubbleContent className="text-base whitespace-pre-wrap">{m.text}</BubbleContent>
                  </Bubble>
                  <MessageFooter>
                    {m.mine ? "Vos" : `${m.from.name} · ${ROLE_LABEL[m.from.role]}`} · {dayTime(m.created_at)}
                    {m.mine && (m.read ? " · Leído" : " · Enviado")}
                  </MessageFooter>
                </MessageContent>
              </Message>
            ))}
            {pending.map((p) => (
              <Message key={p.key} align="end">
                <MessageContent className="gap-1">
                  <Bubble align="end" variant={p.status === "failed" ? "outline" : "default"} className={p.status === "sending" ? "opacity-70" : undefined}>
                    <BubbleContent className="text-base whitespace-pre-wrap">{p.text}</BubbleContent>
                  </Bubble>
                  {p.status === "sending" ? (
                    <MessageFooter>
                      <Spinner className="size-3" /> Enviando…
                    </MessageFooter>
                  ) : (
                    <MessageFooter className="text-destructive">
                      No se envió. {p.error}
                      <Button type="button" variant="link" size="sm" className="h-auto px-1" onClick={() => void deliver(p)}>
                        <RotateCwIcon />
                        Reintentar
                      </Button>
                    </MessageFooter>
                  )}
                </MessageContent>
              </Message>
            ))}
          </MessageGroup>
        )}
        <div ref={bottomRef} />
      </main>
      <form onSubmit={onSubmit} className="sticky bottom-0 border-t bg-card px-3 pt-2.5 pb-[calc(12px+env(safe-area-inset-bottom))]">
        <InputGroup className="h-11 rounded-full bg-background">
          <InputGroupInput
            aria-label="Mensaje"
            placeholder="Escribí un mensaje…"
            className="text-base"
            value={draft}
            maxLength={MAX_CHARS}
            onChange={(e) => setDraft(e.target.value)}
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              type="submit"
              variant="default"
              size="icon-sm"
              className="rounded-full"
              aria-label="Enviar mensaje"
              disabled={!draft.trim()}
            >
              <ArrowRightIcon />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </form>
    </>
  );
}
