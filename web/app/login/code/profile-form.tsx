"use client";
// Name step for a new phone: shown only after /auth/verify answers `profile_required`, i.e. once the code
// proved the person holds the phone. Sends the same code again with the name (docs/contract.md "Auth").
import { useState } from "react";
import { AlertCircleIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export type ProfileDraft = { firstName: string; lastName: string; email: string };

export function ProfileForm({
  draft,
  busy,
  error,
  onSubmit,
}: {
  draft: ProfileDraft;
  busy: boolean;
  error: string | null;
  onSubmit: (draft: ProfileDraft) => void;
}) {
  const [missing, setMissing] = useState<string | null>(null);

  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const next = {
      firstName: String(form.get("firstName") ?? "").trim(),
      lastName: String(form.get("lastName") ?? "").trim(),
      email: String(form.get("email") ?? "").trim(),
    };
    if (!next.firstName) return setMissing("Escribí tu nombre.");
    if (!next.lastName) return setMissing("Escribí tu apellido.");
    setMissing(null);
    onSubmit(next);
  }

  const shown = missing ?? error;
  return (
    <form onSubmit={submit} className="flex flex-1 flex-col gap-7 px-6 pt-2 pb-8" noValidate>
      <p className="text-ink-2">Es tu primera vez en CercanIA. Contanos quién sos para crear tu cuenta.</p>

      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="firstName">Nombre</FieldLabel>
          <Input id="firstName" name="firstName" defaultValue={draft.firstName} autoComplete="given-name" placeholder="Ana" autoFocus required className="h-12 bg-card text-base" />
        </Field>
        <Field>
          <FieldLabel htmlFor="lastName">Apellido</FieldLabel>
          <Input id="lastName" name="lastName" defaultValue={draft.lastName} autoComplete="family-name" placeholder="Pérez" required className="h-12 bg-card text-base" />
        </Field>
        <Field>
          <FieldLabel htmlFor="email">Email (opcional)</FieldLabel>
          <Input id="email" name="email" type="email" defaultValue={draft.email} autoComplete="email" placeholder="ana@ejemplo.com" className="h-12 bg-card text-base" />
          <FieldDescription>Solo para contactarte. Para entrar siempre usás tu celular.</FieldDescription>
        </Field>
      </FieldGroup>

      {shown && (
        <Alert variant="destructive" role="alert">
          <AlertCircleIcon />
          <AlertDescription>{shown}</AlertDescription>
        </Alert>
      )}

      <Button type="submit" size="xl" className="mt-auto" disabled={busy}>
        {busy && <Spinner />}
        {busy ? "Creando tu cuenta…" : "Crear cuenta"}
      </Button>
    </form>
  );
}
