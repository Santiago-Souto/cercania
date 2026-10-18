"use client";

// Record or type the end-of-shift report and show what the backend recorded (CIA-31).
// Nothing here interprets the report: the result shown is exactly the ProcessResult from the backend.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { CircleAlertIcon, CircleCheckIcon, KeyboardIcon, MicIcon, SquareIcon, TriangleAlertIcon } from "lucide-react";
import { BottomBar } from "@/components/app/shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, NETWORK_ERROR_MESSAGE } from "@/lib/api-shared";
import { CHECKLIST_LABEL, duration } from "@/lib/format";
import { newClientId, sendReport, type ReportInput } from "@/lib/send-report";
import type { Alert as AlertT, ProcessResult } from "@/lib/types";

const ITEMS = Object.keys(CHECKLIST_LABEL) as (keyof typeof CHECKLIST_LABEL)[];
// Keeps uploads well under the backend's 4 MB limit at the bitrate below (~1.2 MB).
const MAX_RECORDING_SEC = 5 * 60;
const AUDIO_BITS_PER_SEC = 32_000;

const ALERT_LABEL: Record<AlertT["type"], string> = {
  omission: "Omisión · plan de cuidado",
  change: "Cambio · respecto a lo habitual",
  missing_item: "Checklist incompleto",
  emergency: "Emergencia",
};

type Mode = "voice" | "text";
type Phase = "idle" | "starting" | "recording" | "sending" | "done";

/** First MIME type this browser can record that the backend accepts (Safari only records mp4). */
function recordingType(): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}

function micErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "No tenemos permiso para usar el micrófono. Habilitalo en el navegador o escribí el reporte.";
  if (name === "NotFoundError") return "No encontramos un micrófono en este dispositivo. Podés escribir el reporte.";
  return "No pudimos empezar a grabar. Probá de nuevo o escribí el reporte.";
}

export function ReportComposer({ patientId, children }: { patientId: string; children?: React.ReactNode }) {
  // `children`: static notes rendered below the checklist reminder.
  const [mode, setMode] = useState<Mode>("voice");
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<{ message: string; canType: boolean } | null>(null);
  const [result, setResult] = useState<ProcessResult | null>(null);

  // One client_id per draft (the typed text, the recorded audio): resending the same draft, even after
  // switching modes, reuses it so the backend returns the stored report instead of creating a second one.
  const textClientId = useRef(newClientId());
  const audioClientId = useRef(newClientId());
  // Bumped whenever a pending microphone request becomes obsolete (mode change, unmount).
  const startToken = useRef(0);
  const sending = useRef(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Set when "Enviar reporte" is tapped mid-recording: send as soon as the recorder hands over the audio.
  const sendOnStop = useRef(false);

  useEffect(
    () => () => {
      startToken.current++;
      if (timer.current) clearInterval(timer.current);
      recorder.current?.stream.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  function clearFeedback() {
    setResult(null);
    setError(null);
  }

  async function send(input: ReportInput) {
    if (sending.current) return;
    sending.current = true;
    setPhase("sending");
    setError(null);
    try {
      const clientId = "audio" in input ? audioClientId.current : textClientId.current;
      setResult(await sendReport(patientId, clientId, input));
      setPhase("done");
    } catch (err) {
      // Any failed audio send (transcription, size, format) can fall back to typing.
      setError({ message: err instanceof ApiError ? err.message : NETWORK_ERROR_MESSAGE, canType: "audio" in input });
      setPhase("idle");
    } finally {
      sending.current = false;
    }
  }

  async function startRecording() {
    if (phase !== "idle") return;
    clearFeedback();
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError({ message: "Este navegador no puede grabar audio. Escribí el reporte.", canType: true });
      return;
    }
    const token = ++startToken.current;
    setPhase("starting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (token !== startToken.current) return;
      setPhase("idle");
      setError({ message: micErrorMessage(err), canType: true });
      return;
    }
    if (token !== startToken.current) {
      // The caregiver switched to typing or left while the permission prompt was open.
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    const mimeType = recordingType();
    const rec = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: AUDIO_BITS_PER_SEC });
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      if (timer.current) clearInterval(timer.current);
      const blob = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
      recorder.current = null;
      if (blob.size === 0) {
        setPhase("idle");
        setError({ message: "La grabación quedó vacía. Grabala de nuevo.", canType: true });
        return;
      }
      // A new recording is a new draft, so it gets its own client_id.
      audioClientId.current = newClientId();
      setAudio(blob);
      setPhase("idle");
      if (sendOnStop.current) {
        sendOnStop.current = false;
        void send({ audio: blob });
      }
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setPhase("recording");
    const started = Date.now();
    timer.current = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      setSeconds(s);
      if (s >= MAX_RECORDING_SEC) rec.stop();
    }, 250);
  }

  function stopRecording(thenSend = false) {
    sendOnStop.current = thenSend;
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  // Switching modes keeps both drafts and their client_ids.
  function switchMode(next: Mode) {
    startToken.current++;
    if (phase === "recording") {
      sendOnStop.current = false;
      recorder.current?.stop();
    }
    if (phase === "done" || phase === "starting") setPhase("idle");
    clearFeedback();
    setMode(next);
  }

  function onSend() {
    if (phase === "recording") return stopRecording(true);
    if (mode === "text") return void send({ text: text.trim() });
    if (audio) void send({ audio });
  }

  function another() {
    textClientId.current = newClientId();
    audioClientId.current = newClientId();
    clearFeedback();
    setAudio(null);
    setText("");
    setSeconds(0);
    setPhase("idle");
  }

  // Back to the form with the same content (and client_id: a report that was not stored can be re-sent).
  function retry() {
    setResult(null);
    setPhase("idle");
  }

  if (phase === "done" && result)
    return <ResultView patientId={patientId} result={result} onAnother={another} onRetry={retry} onType={() => switchMode("text")} />;

  const busy = phase === "sending";
  const canSend =
    !busy && phase !== "starting" && (phase === "recording" || (mode === "voice" ? audio !== null : text.trim().length > 0));

  return (
    <>
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        {mode === "voice" ? (
          <Card className="text-base">
            <CardContent className="flex flex-col items-center gap-3 py-2">
              {phase === "recording" ? (
                <Button
                  variant="danger"
                  aria-label="Detener grabación"
                  onClick={() => stopRecording()}
                  className="size-28 animate-pulse rounded-full border-8 border-danger-ring [&_svg]:size-9!"
                >
                  <SquareIcon className="fill-current" />
                </Button>
              ) : (
                <Button
                  variant="danger"
                  aria-label={audio ? "Grabar de nuevo" : "Empezar a grabar"}
                  onClick={startRecording}
                  disabled={busy || phase === "starting"}
                  className="size-28 rounded-full border-8 border-danger-ring [&_svg]:size-9!"
                >
                  <MicIcon />
                </Button>
              )}
              <span className="font-heading text-[28px] font-bold" aria-live="polite">
                {duration(seconds)}
              </span>
              <p className="text-center text-sm text-muted-foreground">
                {phase === "starting"
                  ? "Esperando permiso para usar el micrófono…"
                  : phase === "recording"
                  ? "Grabando… Contá cómo fue el turno con tus palabras. Tocá para terminar."
                  : audio
                    ? "Nota grabada. Enviala o tocá el micrófono para grabar de nuevo."
                    : "Tocá para grabar. Contá cómo fue el turno con tus palabras."}
              </p>
              <Button variant="outline" size="touch" className="font-bold" onClick={() => switchMode("text")} disabled={busy}>
                <KeyboardIcon />
                Prefiero escribirlo
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card className="text-base">
            <CardContent className="flex flex-col gap-3">
              <Field>
                <FieldLabel htmlFor="report-text">¿Cómo fue el turno?</FieldLabel>
                <Textarea
                  id="report-text"
                  autoFocus
                  value={text}
                  disabled={busy}
                  onChange={(e) => {
                    setText(e.target.value);
                    // Edited text is a new draft: the previous id must not return the old result.
                    textClientId.current = newClientId();
                    setError(null);
                  }}
                  placeholder="Ej.: Cenó poco, durmió bien, tomó la medicación de las 20…"
                  className="min-h-40 text-base"
                />
              </Field>
              <Button variant="outline" size="touch" className="self-center font-bold" onClick={() => switchMode("voice")} disabled={busy}>
                <MicIcon />
                Prefiero grabarlo
              </Button>
            </CardContent>
          </Card>
        )}

        {error && (
          <Alert variant="destructive" aria-live="assertive">
            <CircleAlertIcon />
            <AlertTitle>No se envió el reporte</AlertTitle>
            <AlertDescription>
              <p>{error.message}</p>
              {error.canType && mode === "voice" && (
                <Button variant="link" className="h-auto px-0 font-bold" onClick={() => switchMode("text")}>
                  Escribirlo en lugar de grabar
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        <section className="flex flex-col gap-2.5">
          <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">Acordate de contar</h2>
          <div className="grid grid-cols-2 gap-2">
            {ITEMS.map((i) => (
              <Badge key={i} variant="outline" className="h-11 w-full justify-start rounded-xl bg-card px-3 text-sm font-normal">
                {CHECKLIST_LABEL[i]}
              </Badge>
            ))}
          </div>
          <p className="text-[13px] text-muted-foreground">Si te olvidás de algo, te lo preguntamos después.</p>
        </section>

        {children}
      </main>
      <BottomBar>
        <Button size="xl" disabled={!canSend} onClick={onSend}>
          {busy ? (
            <>
              <Spinner />
              {mode === "voice" ? "Enviando y transcribiendo…" : "Enviando…"}
            </>
          ) : (
            "Enviar reporte"
          )}
        </Button>
      </BottomBar>
    </>
  );
}

function ResultView({
  patientId,
  result,
  onAnother,
  onRetry,
  onType,
}: {
  patientId: string;
  result: ProcessResult;
  onAnother: () => void;
  onRetry: () => void;
  onType: () => void;
}) {
  if (result.status !== "ok") {
    // needs_retry / not_a_report / forbidden: nothing was stored; the backend's message says why.
    return (
      <>
        <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
          <Alert variant="warning" className="p-4 text-base">
            <TriangleAlertIcon />
            <AlertTitle>No se registró el reporte</AlertTitle>
            <AlertDescription>{result.message}</AlertDescription>
          </Alert>
          {result.status === "needs_retry" && (
            <Button variant="outline" size="touch" className="font-bold" onClick={onType}>
              <KeyboardIcon />
              Escribirlo
            </Button>
          )}
        </main>
        <BottomBar>
          <Button size="xl" onClick={onRetry}>
            Probar de nuevo
          </Button>
        </BottomBar>
      </>
    );
  }

  const reportHref = `/patients/${patientId}/reports/${result.report.id}` as Route;
  const alerts = result.alerts.filter((a) => a.type !== "missing_item");

  return (
    <>
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4" aria-live="polite">
        {result.red_flag ? (
          <Alert variant="danger">
            <TriangleAlertIcon />
            <AlertTitle className="font-bold">Posible emergencia</AlertTitle>
            <AlertDescription className="whitespace-pre-line">{result.confirmation_text}</AlertDescription>
          </Alert>
        ) : (
          <Card className="text-base">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <CircleCheckIcon className="size-5 text-primary" />
                Reporte registrado
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-line">{result.confirmation_text}</p>
            </CardContent>
          </Card>
        )}

        {result.triage.status === "failed" && (
          <Alert variant="warning">
            <TriangleAlertIcon />
            <AlertDescription>
              No pudimos revisar si hay una emergencia. Si es una emergencia, llamá a emergencias o al médico ahora.
            </AlertDescription>
          </Alert>
        )}

        {result.missing_items.length > 0 && (
          <Card className="text-base">
            <CardContent className="flex flex-col gap-2.5">
              <CardDescription>No mencionaste:</CardDescription>
              <div className="flex flex-wrap gap-2">
                {result.missing_items.map((m) => (
                  <Badge key={m} variant="missing" size="lg">
                    {CHECKLIST_LABEL[m]}
                  </Badge>
                ))}
              </div>
              <CardDescription className="text-[13px]">Podés mandar otra nota contándolo.</CardDescription>
            </CardContent>
          </Card>
        )}

        {alerts.length > 0 && (
          <section className="flex flex-col gap-2.5">
            <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">Alertas</h2>
            {alerts.map((a, i) => (
              <Card key={i} className="gap-2 text-base">
                <CardHeader>
                  <Badge variant={a.type === "emergency" ? "danger" : "warning"}>{ALERT_LABEL[a.type]}</Badge>
                </CardHeader>
                <CardContent>
                  <p>{a.detail}</p>
                  {a.evidence_quote && <p className="text-sm text-muted-foreground italic">“{a.evidence_quote}”</p>}
                  {a.evidence_quote && a.evidence_verified === false && (
                    // Shown, never hidden: an unverified quote does not turn an emergency off (docs/contract.md).
                    <p className="text-sm text-warning-foreground">Esta cita no aparece en la transcripción.</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </section>
        )}

        <Button asChild variant="outline" size="touch" className="font-bold">
          <Link href={reportHref}>Ver reporte</Link>
        </Button>
      </main>
      <BottomBar>
        <Button size="xl" onClick={onAnother}>
          Mandar otra nota
        </Button>
      </BottomBar>
    </>
  );
}
