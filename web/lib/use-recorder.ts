"use client";

// Microphone recording shared by the new report screen (CIA-31) and the patient view (CIA-35).
// Only captures audio: what to do with the recording is up to the caller.
import { useEffect, useRef, useState } from "react";

// Keeps uploads well under the backend's 4 MB limit at the bitrate below (~1.2 MB).
const MAX_RECORDING_SEC = 5 * 60;
const AUDIO_BITS_PER_SEC = 32_000;

export type RecorderState = "idle" | "starting" | "recording";
export type RecorderError = "unsupported" | "denied" | "no_mic" | "failed" | "empty";

/** First MIME type this browser can record that the backend accepts (Safari only records mp4). */
function recordingType(): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}

/** Spanish message for a recorder error; `fallback` says what to do instead, e.g. "escribí el reporte". */
export function recorderErrorMessage(error: RecorderError, fallback: string): string {
  switch (error) {
    case "unsupported":
      return `Este navegador no puede grabar audio. ${capitalize(fallback)}.`;
    case "denied":
      return `No tenemos permiso para usar el micrófono. Habilitalo en el navegador o ${fallback}.`;
    case "no_mic":
      return `No encontramos un micrófono en este dispositivo. ${capitalize(fallback)}.`;
    case "empty":
      return "La grabación quedó vacía. Grabá de nuevo.";
    default:
      return `No pudimos empezar a grabar. Probá de nuevo o ${fallback}.`;
  }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function errorKind(err: unknown): RecorderError {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError") return "no_mic";
  return "failed";
}

/**
 * `onRecorded` gets the audio each time a recording stops (by `stop()` or the time limit).
 * `onError` gets why a recording could not start or came out empty.
 */
export function useRecorder({
  onRecorded,
  onError,
}: {
  onRecorded: (audio: Blob) => void;
  onError: (error: RecorderError) => void;
}) {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  // Bumped whenever a pending microphone request becomes obsolete (cancelStart, unmount).
  const startToken = useRef(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Latest callbacks, so a recording started under an old render still reports to the current one.
  const handlers = useRef({ onRecorded, onError });
  useEffect(() => {
    handlers.current = { onRecorded, onError };
  });

  useEffect(
    () => () => {
      startToken.current++;
      if (timer.current) clearInterval(timer.current);
      recorder.current?.stream.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  async function start() {
    if (state !== "idle") return;
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      handlers.current.onError("unsupported");
      return;
    }
    const token = ++startToken.current;
    setState("starting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (token !== startToken.current) return;
      setState("idle");
      handlers.current.onError(errorKind(err));
      return;
    }
    if (token !== startToken.current) {
      // The user switched to typing or left while the permission prompt was open.
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
      setState("idle");
      if (blob.size === 0) handlers.current.onError("empty");
      else handlers.current.onRecorded(blob);
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    const started = Date.now();
    timer.current = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      setSeconds(s);
      if (s >= MAX_RECORDING_SEC) rec.stop();
    }, 250);
  }

  /** Ends the recording; the audio arrives through `onRecorded`. */
  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  /** Drops a pending microphone request (the permission prompt is still open). */
  function cancelStart() {
    startToken.current++;
    setState((s) => (s === "starting" ? "idle" : s));
  }

  function reset() {
    setSeconds(0);
  }

  return { state, seconds, start, stop, cancelStart, reset };
}
