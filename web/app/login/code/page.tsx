"use client";

// 6-digit SMS code (artboards "Code" and "Link" as the expired state). Ticket: CIA-32.
// POST /auth/verify sets the session cookie; resend repeats /auth/signup (account not created yet) or /auth/login.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { TimerOffIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api-shared";
import {
  authErrorMessage,
  clearPending,
  homeFor,
  loadPending,
  login,
  savePending,
  signup,
  verify,
  type PendingLogin,
} from "@/lib/auth";

/** Codes that make the current code useless: show the "código vencido" state with a resend button. */
const DEAD_CODE = new Set(["code_expired", "too_many_attempts"]);

function mmss(sec: number) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export default function CodePage() {
  const router = useRouter();
  const [login_, setLogin] = useState<PendingLogin | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"verify" | "resend" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dead, setDead] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const p = loadPending();
    if (!p) {
      router.replace("/login");
      return;
    }
    // sessionStorage only exists in the browser: read it after mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLogin(p);
  }, [router]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const waitSec = login_ ? Math.max(0, Math.ceil((login_.resend_at - now) / 1000)) : 0;

  const submit = useCallback(
    async (value: string) => {
      if (!login_ || value.length !== 6 || busy) return;
      setBusy("verify");
      setError(null);
      setNotice(null);
      try {
        const result = await verify(login_.phone, value);
        clearPending();
        // Full load, not router.replace: the layout's notification watcher must restart as the verified user.
        window.location.replace(homeFor(result.memberships));
      } catch (err) {
        const code = err instanceof ApiError ? err.code : "";
        if (DEAD_CODE.has(code)) setDead(authErrorMessage(err));
        else setError(authErrorMessage(err));
        setCode("");
        setBusy(null);
      }
    },
    [login_, busy],
  );

  async function resend() {
    if (!login_ || busy || waitSec > 0) return;
    setBusy("resend");
    setError(null);
    setNotice(null);
    try {
      const sent = login_.signup ? await signup(login_.signup) : await login(login_.phone);
      const next = { ...login_, phone_last4: sent.phone_last4, expires_in_sec: sent.expires_in_sec, resend_at: Date.now() + sent.resend_after_sec * 1000 };
      savePending(next);
      setLogin(next);
      setDead(null);
      setCode("");
      setNotice(`Te mandamos un código nuevo al número terminado en ${sent.phone_last4}.`);
    } catch (err) {
      // Rate limited: restart the countdown so the button is not offered again right away.
      if (err instanceof ApiError && err.code === "too_many_requests") {
        const next = { ...login_, resend_at: Date.now() + 60_000 };
        savePending(next);
        setLogin(next);
      }
      setError(authErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const back = login_ && !login_.signup ? "/login?mode=login" : "/login";
  const minutes = Math.round((login_?.expires_in_sec ?? 600) / 60);
  const resendLabel = waitSec > 0 ? `Pedir otro código en ${mmss(waitSec)}` : "Pedir otro código";

  if (dead) {
    return (
      <AppShell anonymous>
        <TopBar back={back} title="Código vencido" />
        <main className="flex flex-1 flex-col justify-center px-6 pb-8">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <TimerOffIcon />
              </EmptyMedia>
              <EmptyTitle>Este código ya no sirve</EmptyTitle>
              <EmptyDescription>
                {dead} Por seguridad, cada código sirve una sola vez y por pocos minutos.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              {error && (
                <Alert variant="danger-soft" role="alert">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <Button size="xl" onClick={resend} disabled={busy !== null || waitSec > 0}>
                {busy === "resend" && <Spinner />}
                {resendLabel}
              </Button>
              <Button asChild variant="link" size="touch" className="font-bold">
                <Link href={back as Route}>Cambiar número</Link>
              </Button>
            </EmptyContent>
          </Empty>
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell anonymous>
      <TopBar back={back} title="Ingresá el código" />
      <form
        className="flex flex-1 flex-col gap-7 px-6 pt-2 pb-8"
        aria-busy={busy !== null}
        onSubmit={(e) => {
          e.preventDefault();
          submit(code);
        }}
      >
        <p className="text-ink-2">
          Lo mandamos por SMS al número terminado en <strong>{login_?.phone_last4 ?? "····"}</strong>.
        </p>

        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="code">Código de 6 dígitos</FieldLabel>
          <InputOTP
            id="code"
            maxLength={6}
            pattern={REGEXP_ONLY_DIGITS}
            autoComplete="one-time-code"
            inputMode="numeric"
            autoFocus
            value={code}
            onChange={(v) => {
              setCode(v);
              if (error) setError(null);
            }}
            onComplete={submit}
            disabled={busy === "verify" || !login_}
            aria-invalid={error ? true : undefined}
          >
            <InputOTPGroup className="w-full justify-between gap-2">
              {Array.from({ length: 6 }, (_, i) => (
                <InputOTPSlot key={i} index={i} className="h-15 flex-1 rounded-xl! border bg-card font-heading text-2xl font-bold" />
              ))}
            </InputOTPGroup>
          </InputOTP>
          <FieldDescription>El código vence en {minutes} minutos y sirve una sola vez. Si no te llega en un minuto, pedí otro código.</FieldDescription>
        </Field>

        {error && (
          <Alert variant="danger-soft" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {notice && !error && (
          <Alert role="status">
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-between text-sm">
          <Button
            type="button"
            variant="link"
            size="touch"
            className="px-0"
            onClick={resend}
            disabled={busy !== null || waitSec > 0 || !login_}
          >
            {busy === "resend" && <Spinner />}
            {resendLabel}
          </Button>
          <Button asChild variant="link" size="touch" className="px-0 font-bold">
            <Link href={back as Route}>Cambiar número</Link>
          </Button>
        </div>

        <Button type="submit" size="xl" className="mt-auto" disabled={code.length !== 6 || busy !== null}>
          {busy === "verify" && <Spinner />}
          {busy === "verify" ? "Entrando…" : "Entrar"}
        </Button>
      </form>
    </AppShell>
  );
}
