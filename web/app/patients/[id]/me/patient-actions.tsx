"use client";

// The patient's two actions (CIA-35): tell how they feel (voice or text) and "Necesito ayuda".
// What the patient reads back is `message_for_patient`, fixed text written by the backend: never a model answer.
// "Necesito ayuda" is a fixed rule in the backend (AGENTS.md §7); "cómo me siento" goes through triage there.
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlertIcon, CircleCheckIcon, KeyboardIcon, MicIcon, SquareIcon, TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, NETWORK_ERROR_MESSAGE } from "@/lib/api-shared";
import { duration } from "@/lib/format";
import { sendPatientMessage } from "@/lib/send-report";
import type { PatientMessageResult } from "@/lib/types";
import { recorderErrorMessage, useRecorder } from "@/lib/use-recorder";

const EMERGENCY_LINE = "Si es una emergencia, llamá a emergencias.";

type Feeling = { kind: "feeling"; text: string } | { kind: "feeling"; audio: Blob };
type Failure = { title: string; message: string; canType: boolean };

export function PatientActions({ patientId }: { patientId: string }) {
  const router = useRouter();
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  // Help and feelings are tracked apart: a feeling being sent never blocks or hides a help request.
  const [sending, setSending] = useState<"voice" | "text" | null>(null);
  const [helpSending, setHelpSending] = useState(false);
  const [result, setResult] = useState<PatientMessageResult | null>(null);
  const [helpResult, setHelpResult] = useState<PatientMessageResult | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [helpFailure, setHelpFailure] = useState<string | null>(null);
  // Guard double taps: this endpoint has no client id, so a second POST is a second message.
  const feelingInFlight = useRef(false);
  const helpInFlight = useRef(false);

  const recorder = useRecorder({
    onRecorded: (audio) => void sendFeeling("voice", { kind: "feeling", audio }),
    onError: (err) =>
      setFailure({ title: "No pudimos grabar", message: recorderErrorMessage(err, "escribí tu mensaje"), canType: true }),
  });

  async function sendFeeling(via: "voice" | "text", input: Feeling) {
    if (feelingInFlight.current) return;
    feelingInFlight.current = true;
    setSending(via);
    setFailure(null);
    setResult(null);
    try {
      setResult(await sendPatientMessage(patientId, input));
      if (via === "text") {
        setText("");
        setTyping(false);
      }
      router.refresh(); // reload "Tus mensajes" from the backend
    } catch (err) {
      setFailure({
        title: "No se envió tu mensaje",
        message: err instanceof ApiError ? err.message : NETWORK_ERROR_MESSAGE,
        canType: via === "voice",
      });
    } finally {
      feelingInFlight.current = false;
      setSending(null);
    }
  }

  async function sendHelp() {
    if (helpInFlight.current) return;
    helpInFlight.current = true;
    setHelpSending(true);
    setHelpFailure(null);
    setHelpResult(null);
    try {
      setHelpResult(await sendPatientMessage(patientId, { kind: "help" }));
      router.refresh();
    } catch (err) {
      setHelpFailure(err instanceof ApiError ? err.message : NETWORK_ERROR_MESSAGE);
    } finally {
      helpInFlight.current = false;
      setHelpSending(false);
    }
  }

  function onVoice() {
    if (recorder.state === "recording") return recorder.stop();
    setFailure(null);
    setResult(null);
    void recorder.start();
  }

  function startTyping() {
    recorder.cancelStart();
    setFailure(null);
    setResult(null);
    setTyping(true);
  }

  const busy = sending !== null;
  const recording = recorder.state === "recording";

  return (
    <>
      {result && <ResultAlert result={result} />}

      {failure && (
        <Alert variant="destructive" role="alert" className="p-4 text-lg">
          <CircleAlertIcon />
          <AlertTitle className="font-bold">{failure.title}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 text-lg">
            <p>{failure.message}</p>
            {/* Backend messages for audio failures already say it; never show the line twice. */}
            {!/emergencia/i.test(failure.message) && <p className="font-bold">{EMERGENCY_LINE}</p>}
            {failure.canType && !typing && (
              <Button variant="outline-primary" className="h-16 rounded-2xl text-lg font-bold" onClick={startTyping}>
                <KeyboardIcon />
                Escribirlo
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      {typing ? (
        <Card className="text-[19px]">
          <CardContent className="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor="feeling-text" className="text-[19px]">
                ¿Cómo te sentís?
              </FieldLabel>
              <Textarea
                id="feeling-text"
                autoFocus
                value={text}
                maxLength={1000}
                disabled={busy}
                onChange={(e) => setText(e.target.value)}
                placeholder="Ej.: Hoy me duele un poco la rodilla"
                className="min-h-36 text-[19px]!"
              />
            </Field>
            <Button
              className="h-16 rounded-2xl text-[19px] font-bold"
              disabled={busy || text.trim().length === 0}
              onClick={() => void sendFeeling("text", { kind: "feeling", text: text.trim() })}
            >
              {sending === "text" ? (
                <>
                  <Spinner />
                  Enviando…
                </>
              ) : (
                "Enviar"
              )}
            </Button>
            <Button variant="outline" className="h-16 rounded-2xl text-[19px] font-bold" disabled={busy} onClick={() => setTyping(false)}>
              <MicIcon />
              Prefiero hablar
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <Button
            aria-label={recording ? "Terminar y enviar" : "Contar cómo me siento"}
            disabled={busy || recorder.state === "starting"}
            onClick={onVoice}
            variant={recording ? "danger" : "default"}
            className="h-auto min-h-56 flex-col gap-3 rounded-[28px] py-6 whitespace-normal"
          >
            <span className="flex size-22 items-center justify-center rounded-full bg-card text-primary">
              {sending === "voice" ? (
                <Spinner className="size-10!" />
              ) : recording ? (
                <SquareIcon className="size-10! animate-pulse fill-danger text-danger" />
              ) : (
                <MicIcon className="size-10!" />
              )}
            </span>
            <span className="font-heading text-2xl font-bold" aria-live="polite">
              {sending === "voice"
                ? "Enviando…"
                : recording
                  ? `Grabando · ${duration(recorder.seconds)}`
                  : "Contar cómo me siento"}
            </span>
            <span className="text-base font-normal">
              {recorder.state === "starting"
                ? "Esperando permiso para usar el micrófono…"
                : sending === "voice"
                  ? "Estamos escuchando tu mensaje"
                  : recording
                    ? "Tocá para terminar y enviar"
                    : "Tocá y hablá"}
            </span>
          </Button>

          <Button
            variant="outline-primary"
            className="h-16 rounded-2xl text-[19px] font-bold"
            disabled={busy || recording}
            onClick={startTyping}
          >
            Prefiero escribir
          </Button>
        </>
      )}

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            variant="danger"
            disabled={helpSending}
            className="h-22 rounded-3xl font-heading text-2xl font-bold [&_svg]:size-8!"
          >
            {helpSending ? (
              <>
                <Spinner />
                Avisando…
              </>
            ) : (
              <>
                <TriangleAlertIcon />
                Necesito ayuda
              </>
            )}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-2xl">¿Avisamos a tu equipo?</AlertDialogTitle>
            <AlertDialogDescription className="text-lg">
              Les llega un mensaje ahora mismo. {EMERGENCY_LINE}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            {/* `!`: Slot concatenates classes without tailwind-merge, so the button's default height would win otherwise. */}
            <AlertDialogCancel className="h-16! text-lg!">No, volver</AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              className="h-16! text-lg! font-bold"
              onClick={() => void sendHelp()}
            >
              Sí, pedir ayuda
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Right under the button the patient just pressed. */}
      {helpResult && <ResultAlert result={helpResult} />}

      {helpFailure && (
        <Alert variant="destructive" role="alert" className="p-4 text-lg">
          <CircleAlertIcon />
          <AlertTitle className="font-bold">No pudimos avisar a tu equipo</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 text-lg">
            <p>{helpFailure}</p>
            <p className="font-bold">{EMERGENCY_LINE}</p>
            <Button variant="danger" className="h-16 rounded-2xl text-lg font-bold" disabled={helpSending} onClick={() => void sendHelp()}>
              Probar de nuevo
            </Button>
          </AlertDescription>
        </Alert>
      )}
    </>
  );
}

function ResultAlert({ result }: { result: PatientMessageResult }) {
  // Help and red flags read as urgent; a plain feeling is a calm confirmation. Text is the backend's, verbatim.
  if (result.kind === "help" || result.red_flag) {
    return (
      <Alert variant="danger" role="alert">
        <TriangleAlertIcon />
        <AlertTitle className="text-xl font-bold">{result.kind === "help" ? "Pediste ayuda" : "Avisamos a tu equipo"}</AlertTitle>
        <AlertDescription className="text-[19px]">{result.message_for_patient}</AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert role="alert" className="rounded-xl p-4 text-[19px]">
      <CircleCheckIcon className="size-6! text-primary" />
      <AlertTitle className="text-xl font-bold">Mensaje enviado</AlertTitle>
      <AlertDescription className="text-[19px] text-foreground">{result.message_for_patient}</AlertDescription>
    </Alert>
  );
}
