"use client";

// Sign-up / login form: POST /auth/signup or /auth/login, then /login/code. Ticket: CIA-32.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { authErrorMessage, login, savePending, signup, type SignupInput } from "@/lib/auth";

export function LoginForm({ isLogin, notice }: { isLogin: boolean; notice?: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const phone = String(data.get("phone") ?? "").trim();
    const input: SignupInput | undefined = isLogin
      ? undefined
      : { name: String(data.get("name") ?? "").trim(), phone, email: String(data.get("email") ?? "").trim() || undefined };
    setPending(true);
    setError(null);
    try {
      const sent = input ? await signup(input) : await login(phone);
      savePending({
        phone,
        phone_last4: sent.phone_last4,
        signup: input,
        expires_in_sec: sent.expires_in_sec,
        resend_at: Date.now() + sent.resend_after_sec * 1000,
      });
      router.push("/login/code");
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-1 flex-col gap-7" aria-busy={pending}>
      {notice && !error && (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      <FieldGroup>
        {!isLogin && (
          <Field>
            <FieldLabel htmlFor="name">Nombre</FieldLabel>
            <Input id="name" name="name" required maxLength={120} autoComplete="name" placeholder="Ana Pérez" className="h-12 bg-card text-base" />
          </Field>
        )}
        {!isLogin && (
          <Field>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input id="email" name="email" type="email" autoComplete="email" placeholder="ana@ejemplo.com" className="h-12 bg-card text-base" />
          </Field>
        )}
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="phone">Celular</FieldLabel>
          <Input
            id="phone"
            name="phone"
            type="tel"
            required
            autoComplete="tel"
            inputMode="tel"
            placeholder="+598 9X XXX XXX"
            aria-invalid={error ? true : undefined}
            className="h-12 bg-card text-base"
          />
          <FieldDescription>Con código de país. Ahí te llega el código por SMS. Con este mismo número mandás los reportes por WhatsApp.</FieldDescription>
        </Field>
      </FieldGroup>

      {error && (
        <Alert variant="danger-soft" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="mt-auto flex flex-col gap-3">
        <Button type="submit" size="xl" disabled={pending}>
          {pending && <Spinner />}
          {pending ? "Enviando código…" : "Enviar código por SMS"}
        </Button>
        <p className="text-center text-[13px] text-muted-foreground">Al continuar aceptás recibir el código por SMS y mensajes de CercanIA por WhatsApp.</p>
      </div>
    </form>
  );
}
