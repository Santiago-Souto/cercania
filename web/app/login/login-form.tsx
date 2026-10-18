"use client";
// Sign-up / login form: POST /auth/signup or /auth/login, then the code screen (CIA-32).
import { useState } from "react";
import { useRouter } from "next/navigation";
import { isPossiblePhoneNumber } from "react-phone-number-input";
import { AlertCircleIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PhoneInput } from "@/components/ui/phone-input";
import { Spinner } from "@/components/ui/spinner";
import { authErrorMessage, requestCode, safeNext, savePending } from "@/lib/auth";

const NAME_MISSING = "Escribí tu nombre.";

export function LoginForm({ mode, next }: { mode: "signup" | "login"; next?: string }) {
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | undefined>();
  const [country, setCountry] = useState<string | undefined>("UY");
  const isLogin = mode === "login";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (sending) return; // Enter in the field while a code is on its way must not send a second SMS
    const form = new FormData(e.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const email = String(form.get("email") ?? "").trim();
    if (!isLogin && !name) return setError(NAME_MISSING);
    if (!phone) return setError("Escribí tu celular.");
    if (!isPossiblePhoneNumber(phone)) return setError("Revisá el número: le faltan o le sobran números para ese país.");

    setSending(true);
    setError(null);
    try {
      const sent = await requestCode({ mode, phone, name, email });
      savePending({ mode, phone, name, email, next: safeNext(next), sent, sentAt: Date.now() });
      router.push("/login/code");
    } catch (err) {
      setError(authErrorMessage(err));
      setSending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-1 flex-col gap-7" noValidate>
      <FieldGroup>
        {!isLogin && (
          <Field>
            <FieldLabel htmlFor="name">Nombre</FieldLabel>
            <Input id="name" name="name" autoComplete="name" placeholder="Ana Pérez" required className="h-12 bg-card text-base" />
          </Field>
        )}
        {!isLogin && (
          <Field>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input id="email" name="email" type="email" autoComplete="email" placeholder="ana@ejemplo.com" className="h-12 bg-card text-base" />
          </Field>
        )}
        <Field>
          <FieldLabel htmlFor="phone">Celular</FieldLabel>
          <PhoneInput
            id="phone"
            value={phone}
            onChange={setPhone}
            onCountryChange={setCountry}
            autoComplete="tel"
            placeholder={country === "UY" ? "099 123 456" : "Número de celular"}
            required
            aria-invalid={!!error && error !== NAME_MISSING}
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
