"use client";

// 6-digit WhatsApp code (artboards "Code" and "Link" as the expired state). Ticket: CIA-32.
// Skeleton: POST /auth/verify, resend countdown and error states land in CIA-32.
import Link from "next/link";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { AppShell, TopBar } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";

export default function CodePage() {
  return (
    <AppShell>
      <TopBar back="/login" title="Ingresá el código" />
      <main className="flex flex-1 flex-col gap-7 px-6 pt-2 pb-8">
        <p className="text-ink-2">
          Lo mandamos por WhatsApp al número terminado en <strong>0000</strong>.
        </p>

        <Field>
          <FieldLabel htmlFor="code">Código de 6 dígitos</FieldLabel>
          <InputOTP id="code" maxLength={6} pattern={REGEXP_ONLY_DIGITS} autoComplete="one-time-code" inputMode="numeric">
            <InputOTPGroup className="w-full justify-between gap-2">
              {Array.from({ length: 6 }, (_, i) => (
                <InputOTPSlot key={i} index={i} className="h-15 flex-1 rounded-xl! border bg-card font-heading text-2xl font-bold" />
              ))}
            </InputOTPGroup>
          </InputOTP>
          <FieldDescription>El código vence en 10 minutos y sirve una sola vez. Si no te llega, mandale “hola” al bot y pedí otro código.</FieldDescription>
        </Field>

        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Reenviar en 0:60</span>
          <Button asChild variant="link" size="touch" className="px-0 font-bold">
            <Link href="/login">Cambiar número</Link>
          </Button>
        </div>

        <Button asChild size="xl" className="mt-auto">
          <Link href="/patients">Entrar</Link>
        </Button>
      </main>
    </AppShell>
  );
}
