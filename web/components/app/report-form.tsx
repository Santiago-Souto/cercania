"use client";
// Text report from the web: POST /patients/{id}/reports. Audio recording lands in CIA-31.
// On an emergency the reply is the fixed text written in code by the backend (confirmation_text).
import { useRef, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { CheckCircle2Icon, TriangleAlertIcon } from "lucide-react";
import { BottomBar } from "@/components/app/shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ClientApiError, sendTextReport } from "@/lib/client-api";
import type { ProcessResult } from "@/lib/types";

const EMERGENCY_FALLBACK = "⚠️ Si es una emergencia, llamá a emergencias o al médico ahora.";

export function ReportForm({ patientId }: { patientId: string }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessResult | null>(null);
  // One id per submission; kept across retries of the same text so the backend dedupes a double send.
  const clientId = useRef<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (sending || !text.trim()) return;
    clientId.current ??= `web_${crypto.randomUUID()}`;
    setSending(true);
    setError(null);
    try {
      setResult(await sendTextReport(patientId, clientId.current, text.trim()));
      clientId.current = null;
    } catch (err) {
      setError(err instanceof ClientApiError ? err.message : "No pudimos enviar el reporte. Probá de nuevo.");
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setText("");
    setResult(null);
    clientId.current = null;
  }

  if (result) {
    const ok = result.status === "ok";
    const emergency = ok && (result.red_flag || result.triage?.status === "failed");
    const message = ok ? result.confirmation_text || (emergency ? EMERGENCY_FALLBACK : "Registrado.") : result.message;
    return (
      <>
        <main className="flex flex-1 flex-col gap-4 px-4 pb-4" aria-live="polite">
          <Alert variant={emergency ? "danger" : ok ? "default" : "warning"}>
            {emergency ? <TriangleAlertIcon /> : <CheckCircle2Icon />}
            <AlertTitle className="font-heading text-lg font-bold">
              {emergency ? "Emergencia" : ok ? "Reporte registrado" : "No se registró"}
            </AlertTitle>
            <AlertDescription className="text-[15px]">{message}</AlertDescription>
          </Alert>
          {ok && result.red_flag && (
            <p className="text-sm text-muted-foreground">Avisamos a la familia y al resto del equipo de este paciente.</p>
          )}
        </main>
        <BottomBar>
          <div className="flex flex-col gap-2">
            {ok && (
              <Button asChild size="xl">
                <Link href={`/patients/${patientId}/reports/${result.report.id}` as Route}>Ver el reporte</Link>
              </Button>
            )}
            <Button variant="outline" size="touch" className="font-bold" onClick={reset}>
              Enviar otra nota
            </Button>
          </div>
        </BottomBar>
      </>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-1 flex-col">
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <Textarea
          aria-label="Reporte del turno"
          placeholder="Contá cómo fue el turno con tus palabras…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={sending}
          className="min-h-40 bg-card text-base"
        />
        {error && (
          <Alert variant="danger" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </main>
      <BottomBar>
        <Button type="submit" size="xl" disabled={sending || !text.trim()}>
          {sending ? (
            <>
              <Spinner /> Enviando…
            </>
          ) : (
            "Enviar reporte"
          )}
        </Button>
      </BottomBar>
    </form>
  );
}
