"use client";

// 6-digit SMS code (artboards "Code" and "Link" as the expired state). Ticket: CIA-32.
// POST /auth/verify sets the session cookie; resend counts down from resend_after_sec.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { AlertCircleIcon, TimerOffIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { Spinner } from "@/components/ui/spinner";
import {
  authErrorMessage,
  clearPending,
  isDeadCode,
  landingFor,
  loadPending,
  requestCode,
  savePending,
  verifyCode,
  type PendingLogin,
} from "@/lib/auth";

function secondsLeft(p: PendingLogin, now: number): number {
  return Math.max(0, Math.ceil(p.sent.resend_after_sec - (now - p.sentAt) / 1000));
}

function clock(sec: number): string {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export default function CodePage() {
  const router = useRouter();
  const [pending, setPending] = useState<PendingLogin | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"verify" | "resend" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dead, setDead] = useState<string | null>(null); // "código vencido" state

  useEffect(() => {
    // sessionStorage is browser-only: read after mount. No pending login -> start over.
    const p = loadPending();
    if (!p) {
      router.replace("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(p);
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [router]);

  async function verify(value: string) {
    if (!pending || busy) return;
    setBusy("verify");
    setError(null);
    try {
      const res = await verifyCode(pending.phone, value);
      clearPending();
      // Full load: server components and the notification poller start fresh with the new cookie.
      window.location.assign(landingFor(res.memberships, pending.next));
    } catch (err) {
      setCode("");
      if (isDeadCode(err)) setDead(authErrorMessage(err));
      else setError(authErrorMessage(err));
      setBusy(null);
    }
  }

  async function resend() {
    if (!pending || busy) return;
    setBusy("resend");
    setError(null);
    try {
      const sent = await requestCode(pending);
      const next = { ...pending, sent, sentAt: Date.now() };
      savePending(next);
      setPending(next);
      setNow(Date.now());
      setDead(null);
      setCode("");
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (!pending) {
    return (
      <AppShell publicPage>
        <TopBar back="/login" title="Ingresá el código" />
      </AppShell>
    );
  }

  const wait = secondsLeft(pending, now);
  const minutes = Math.round(pending.sent.expires_in_sec / 60);
  const back = pending.mode === "login" ? "/login?mode=login" : "/login";
  const resendButton = (
    <Button type="button" variant="link" size="touch" className="px-0 font-bold" disabled={wait > 0 || busy !== null} onClick={resend}>
      {busy === "resend" && <Spinner />}
      {wait > 0 ? `Reenviar en ${clock(wait)}` : "Pedir código nuevo"}
    </Button>
  );

  if (dead) {
    return (
      <AppShell publicPage>
        <TopBar back={back} title="Código vencido" />
        <main className="flex flex-1 flex-col px-6 pt-2 pb-8">
          <Empty className="flex-1">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <TimerOffIcon />
              </EmptyMedia>
              <EmptyTitle>Este código ya no sirve</EmptyTitle>
              <EmptyDescription>
                {dead} Por seguridad, cada código sirve una sola vez y por {minutes} minutos.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              {error && (
                <Alert variant="destructive" role="alert">
                  <AlertCircleIcon />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              {resendButton}
            </EmptyContent>
          </Empty>
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell publicPage>
      <TopBar back={back} title="Ingresá el código" />
      <form
        className="flex flex-1 flex-col gap-7 px-6 pt-2 pb-8"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.length === 6) verify(code);
        }}
      >
        <p className="text-ink-2">
          Lo mandamos por SMS al número terminado en <strong>{pending.sent.phone_last4}</strong>.
        </p>

        <Field>
          <FieldLabel htmlFor="code">Código de 6 dígitos</FieldLabel>
          <InputOTP
            id="code"
            maxLength={6}
            pattern={REGEXP_ONLY_DIGITS}
            autoComplete="one-time-code"
            inputMode="numeric"
            autoFocus
            value={code}
            onChange={setCode}
            onComplete={verify}
            disabled={busy === "verify"}
          >
            <InputOTPGroup className="w-full justify-between gap-2">
              {Array.from({ length: 6 }, (_, i) => (
                <InputOTPSlot key={i} index={i} className="h-15 flex-1 rounded-xl! border bg-card font-heading text-2xl font-bold" />
              ))}
            </InputOTPGroup>
          </InputOTP>
          <FieldDescription>
            El código vence en {minutes} minutos y sirve una sola vez. Si no te llega en un minuto, pedí otro código.
          </FieldDescription>
        </Field>

        {error && (
          <Alert variant="destructive" role="alert">
            <AlertCircleIcon />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-between text-sm">
          {resendButton}
          <Button type="button" variant="link" size="touch" className="px-0 font-bold" onClick={() => router.push(back as Route)}>
            Cambiar número
          </Button>
        </div>

        <Button type="submit" size="xl" className="mt-auto" disabled={code.length < 6 || busy !== null}>
          {busy === "verify" && <Spinner />}
          {busy === "verify" ? "Entrando…" : "Entrar"}
        </Button>
      </form>
    </AppShell>
  );
}
