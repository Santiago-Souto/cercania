"use client";
// Phone form, the same for sign-up and login: POST /auth/login, then the code screen. A new phone gives
// its name after the code (code/page.tsx).
import { useState } from "react";
import { useRouter } from "next/navigation";
import { isPossiblePhoneNumber } from "react-phone-number-input";
import { AlertCircleIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { PhoneInput } from "@/components/ui/phone-input";
import { Spinner } from "@/components/ui/spinner";
import { authErrorMessage, requestCode, safeNext, savePending } from "@/lib/auth";

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | undefined>();
  const [country, setCountry] = useState<string | undefined>("UY");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!phone) return setError("Escribí tu celular.");
    if (!isPossiblePhoneNumber(phone)) return setError("Revisá el número: le faltan o le sobran números para ese país.");

    setSending(true);
    setError(null);
    try {
      const sent = await requestCode(phone);
      savePending({ phone, next: safeNext(next), sent, sentAt: Date.now() });
      router.push("/login/code");
    } catch (err) {
      setError(authErrorMessage(err));
      setSending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-1 flex-col gap-7" noValidate>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="phone">Celular</FieldLabel>
          <PhoneInput
            id="phone"
            value={phone}
            onChange={setPhone}
            onCountryChange={setCountry}
            autoComplete="tel"
            autoFocus
            placeholder={country === "UY" ? "099 123 456" : "Número de celular"}
            required
            aria-invalid={!!error && !phone}
            numberInputProps={{ className: "h-12 bg-card text-base" }}
          />
          <FieldDescription>Ahí te llega el código por SMS. Con este mismo número te pueden invitar a un paciente.</FieldDescription>
        </Field>
      </FieldGroup>

      {error && (
        <Alert variant="destructive" role="alert">
          <AlertCircleIcon />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="mt-auto flex flex-col gap-3">
        <Button type="submit" size="xl" disabled={sending}>
          {sending && <Spinner />}
          {sending ? "Enviando código…" : "Enviar código por SMS"}
        </Button>
        <p className="text-center text-[13px] text-muted-foreground">Al continuar aceptás recibir el código por SMS.</p>
      </div>
    </form>
  );
}
