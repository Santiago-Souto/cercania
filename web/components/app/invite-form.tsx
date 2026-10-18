"use client";
// "Invitar a alguien" (artboard "AddPatient"): WhatsApp number + role. Used on the new-patient form
// (queues the invite until the patient is saved) and on the team page (sends it right away). CIA-34.
// Not a <form>: it lives inside the new-patient form, and nested forms are invalid HTML.

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { ROLE_LABEL } from "@/lib/format";
import { checkPhone, ROLE_HELP, ROLES } from "@/lib/team";
import type { Role } from "@/lib/types";

/** Resolves to an error message to show next to the number, or null when the invite was taken. */
export type OnInvite = (phone: string, role: Role) => Promise<string | null> | string | null;

export function InviteForm({ onInvite, submitLabel }: { onInvite: OnInvite; submitLabel: string }) {
  const id = useId();
  const [contact, setContact] = useState("");
  const [role, setRole] = useState<Role>("family");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit() {
    if (pending) return; // Enter on the number field must not send a second invite while one is in flight
    const checked = checkPhone(contact);
    if ("error" in checked) {
      setError(checked.error);
      return;
    }
    setPending(true);
    try {
      const err = await onInvite(checked.phone, role);
      setError(err);
      if (!err) setContact("");
    } finally {
      setPending(false);
    }
  }

  return (
    <Card size="sm" className="bg-background ring-0">
      <CardHeader>
        <CardTitle className="text-sm font-bold">Invitar a alguien</CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-3">
          <Field data-invalid={!!error || undefined}>
            <FieldLabel htmlFor={`${id}-phone`}>WhatsApp</FieldLabel>
            <Input
              id={`${id}-phone`}
              type="tel"
              inputMode="tel"
              autoComplete="off"
              placeholder="+598 9X XXX XXX"
              className="h-12 bg-card text-base"
              value={contact}
              aria-invalid={!!error || undefined}
              onChange={(e) => {
                setContact(e.target.value);
                setError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void submit();
                }
              }}
            />
            {error ? <FieldError>{error}</FieldError> : <FieldDescription>Ve la invitación en Cercanía cuando entra con ese número. No se invita por email.</FieldDescription>}
          </Field>
          <Field>
            <FieldLabel htmlFor={`${id}-role`}>Rol</FieldLabel>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger id={`${id}-role`} className="h-12! w-full bg-card text-base">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldDescription>{ROLE_HELP[role]}</FieldDescription>
          </Field>
          <Button type="button" variant="outline-primary" size="touch" className="w-full" disabled={pending} onClick={() => void submit()}>
            {pending && <Spinner />}
            {submitLabel}
          </Button>
        </FieldGroup>
      </CardContent>
    </Card>
  );
}
