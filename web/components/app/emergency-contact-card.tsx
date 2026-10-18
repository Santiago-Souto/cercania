"use client";
// "Número de emergencia" on the patient page, with "Editar" for caregiver and doctor (CIA-51).
// The backend checks the permission; this only hides the button from roles that cannot use it.

import { useState, useTransition } from "react";
import { PencilIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { updateEmergencyContactAction } from "@/app/patients/actions";
import { checkPhone, MAX_TEXT } from "@/lib/team";
import type { EmergencyContact } from "@/lib/types";
import { DEFAULT_EMERGENCY_NUMBER, EmergencyCallButton } from "./emergency-call";

export function EmergencyContactCard({ patientId, contact, canEdit }: { patientId: string; contact: EmergencyContact | null; canEdit: boolean }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(contact?.name ?? "");
  const [phone, setPhone] = useState(contact?.phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  function save(next: { name: string; phone: string } | null) {
    setError(null);
    if (next) {
      if (!next.name.trim()) return setError("Escribí a quién corresponde el número.");
      if (next.name.trim().length > MAX_TEXT) return setError(`Hasta ${MAX_TEXT} caracteres.`);
      const checked = checkPhone(next.phone);
      if ("error" in checked) return setError(checked.error);
      next = { name: next.name.trim(), phone: checked.phone };
    }
    startSaving(async () => {
      try {
        const res = await updateEmergencyContactAction(patientId, next);
        if ("error" in res) setError(res.error.message);
        else {
          setName(next?.name ?? "");
          setPhone(next?.phone ?? "");
          setEditing(false);
        }
      } catch {
        setError("No pudimos guardar el número. Revisá tu conexión y probá de nuevo.");
      }
    });
  }

  return (
    <Card className="text-base">
      <CardHeader className="flex items-center justify-between gap-3">
        <CardTitle className="text-lg font-semibold">Número de emergencia</CardTitle>
        {canEdit && !editing && (
          <Button type="button" variant="ghost" size="touch" className="font-bold text-primary" onClick={() => setEditing(true)}>
            <PencilIcon />
            Editar
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {editing ? (
          <FieldGroup className="gap-3">
            <Field data-invalid={!!error || undefined}>
              <FieldLabel htmlFor="ec-name">Nombre</FieldLabel>
              <Input id="ec-name" className="h-12 text-base" placeholder="Emergencias Residencia" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field data-invalid={!!error || undefined}>
              <FieldLabel htmlFor="ec-phone">Teléfono</FieldLabel>
              <Input id="ec-phone" type="tel" inputMode="tel" className="h-12 text-base" placeholder="+598 99 123 456" autoComplete="off" value={phone} aria-invalid={!!error || undefined} onChange={(e) => setPhone(e.target.value)} />
              {error ? <FieldError>{error}</FieldError> : <FieldDescription>Con código de país. Sin número, la app ofrece llamar al {DEFAULT_EMERGENCY_NUMBER}.</FieldDescription>}
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="touch" disabled={saving} onClick={() => save({ name, phone })}>
                {saving && <Spinner />}
                Guardar
              </Button>
              <Button type="button" variant="outline" size="touch" disabled={saving} onClick={() => { setEditing(false); setError(null); setName(contact?.name ?? ""); setPhone(contact?.phone ?? ""); }}>
                Cancelar
              </Button>
              {contact && (
                <Button type="button" variant="ghost" size="touch" disabled={saving} onClick={() => save(null)}>
                  Quitar número
                </Button>
              )}
            </div>
          </FieldGroup>
        ) : (
          <>
            <p className="text-sm">
              {contact ? (
                <>
                  <span className="font-bold">{contact.name}</span> · {contact.phone}
                </>
              ) : (
                <span className="text-muted-foreground">Sin número cargado: en una emergencia la app ofrece llamar al {DEFAULT_EMERGENCY_NUMBER}.</span>
              )}
            </p>
            <EmergencyCallButton contact={contact} className="self-start" />
          </>
        )}
      </CardContent>
    </Card>
  );
}
