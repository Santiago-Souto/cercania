"use client";
// Add patient + team form (artboard "AddPatient"). Ticket: CIA-34.
// The patient joins with the phone set under "Datos"; the team section only queues family invites.
// Doses are stored exactly as typed; CercanIA never computes or suggests them (AGENTS.md section 7).

import Link from "next/link";
import type { Route } from "next";
import { useState, useTransition } from "react";
import { PlusIcon, XIcon } from "lucide-react";
import { InviteForm } from "@/components/app/invite-form";
import { TeamList } from "@/components/app/team-list";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PhoneInput } from "@/components/ui/phone-input";
import { Item, ItemActions, ItemContent } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { checkPhone, MAX_TEXT, parseTimes } from "@/lib/team";
import type { NewPatient, Role } from "@/lib/types";
import { createPatientAction, type CreatePatientResult } from "../actions";

type MedRow = { key: number; name: string; dose: string; times: string };
type TextRow = { key: number; text: string };
type Errors = Record<string, string>;

let nextKey = 1;
const key = () => nextKey++;

/** Builds the POST /patients body, or the errors to show next to each field. */
function validate(name: string, location: string, phone: string | undefined, ecName: string, ecPhone: string, meds: MedRow[], indications: TextRow[], allergies: TextRow[]): { body: NewPatient } | { errors: Errors } {
  const errors: Errors = {};
  const tooLong = `Hasta ${MAX_TEXT} caracteres.`;
  if (!name.trim()) errors.name = "Escribí el nombre del paciente.";
  else if (name.trim().length > MAX_TEXT) errors.name = tooLong;
  if (location.trim().length > MAX_TEXT) errors.location = tooLong;

  let emergency_contact: NewPatient["emergency_contact"] = null;
  if (ecName.trim() || ecPhone.trim()) {
    if (!ecName.trim()) errors.ecName = "Escribí a quién corresponde el número.";
    else if (ecName.trim().length > MAX_TEXT) errors.ecName = tooLong;
    const p = checkPhone(ecPhone);
    if ("error" in p) errors.ecPhone = p.error;
    else if (!errors.ecName) emergency_contact = { name: ecName.trim(), phone: p.phone };
  }

  const medications: NewPatient["care_plan"]["medications"] = [];
  for (const m of meds) {
    if (!m.name.trim() && !m.dose.trim() && !m.times.trim()) continue; // untouched row
    if (!m.name.trim()) errors[`med-${m.key}-name`] = "Falta el nombre.";
    else if (m.name.trim().length > MAX_TEXT) errors[`med-${m.key}-name`] = tooLong;
    if (!m.dose.trim()) errors[`med-${m.key}-dose`] = "Falta la dosis, tal como la indicó el médico.";
    else if (m.dose.trim().length > MAX_TEXT) errors[`med-${m.key}-dose`] = tooLong;
    const t = parseTimes(m.times);
    if ("error" in t) errors[`med-${m.key}-times`] = t.error;
    else medications.push({ name: m.name.trim(), dose: m.dose.trim(), times: t.times });
  }
  const lines = (rows: TextRow[], prefix: string) => {
    const out: string[] = [];
    for (const r of rows) {
      const v = r.text.trim();
      if (!v) continue;
      if (v.length > 300) errors[`${prefix}-${r.key}`] = "Hasta 300 caracteres.";
      out.push(v);
    }
    return out;
  };
  const body: NewPatient = {
    display_name: name.trim(),
    location: location.trim() || null,
    phone: phone || null,
    emergency_contact,
    care_plan: { medications, indications: lines(indications, "ind"), allergies: lines(allergies, "all") },
  };
  return Object.keys(errors).length ? { errors } : { body };
}

export function NewPatientForm() {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [phone, setPhone] = useState<string | undefined>();
  const patientPhone = phone; // E.164 from PhoneInput; the invite callback below shadows `phone`
  const [ecName, setEcName] = useState("");
  const [ecPhone, setEcPhone] = useState("");
  const [meds, setMeds] = useState<MedRow[]>([]);
  const [indications, setIndications] = useState<TextRow[]>([]);
  const [allergies, setAllergies] = useState<TextRow[]>([]);
  const [invites, setInvites] = useState<{ phone: string; role: Role }[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Extract<CreatePatientResult, { patientId: string }> | null>(null);
  const [saving, startSaving] = useTransition();

  const clear = (k: string) =>
    setErrors((prev) => {
      if (!(k in prev)) return prev;
      const next = { ...prev };
      delete next[k];
      return next;
    });
  const fieldProps = (k: string) => ({ "data-invalid": !!errors[k] || undefined });
  const inputProps = (k: string) => ({ "aria-invalid": !!errors[k] || undefined });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (saved) return;
    setFormError(null);
    const v = validate(name, location, phone, ecName, ecPhone, meds, indications, allergies);
    if ("errors" in v) {
      setErrors(v.errors);
      setFormError("Revisá los campos marcados.");
      return;
    }
    setErrors({});
    startSaving(async () => {
      try {
        const res = await createPatientAction(v.body, invites.map((i) => ({ contact: i.phone, role: i.role })));
        // On full success the action redirects to the new patient and never returns here.
        if ("error" in res) setFormError(res.error.message);
        else setSaved(res);
      } catch {
        setFormError("No pudimos guardar el paciente. Revisá tu conexión y probá de nuevo.");
      }
    });
  }

  const textList = (rows: TextRow[], set: (r: TextRow[]) => void, prefix: string, label: string, placeholder: string) =>
    rows.map((r, i) => (
      <Field key={r.key} {...fieldProps(`${prefix}-${r.key}`)}>
        <div className="flex items-center gap-2">
          <Input
            aria-label={`${label} ${i + 1}`}
            placeholder={placeholder}
            className="h-12 text-base"
            value={r.text}
            {...inputProps(`${prefix}-${r.key}`)}
            onChange={(e) => {
              set(rows.map((x) => (x.key === r.key ? { ...x, text: e.target.value } : x)));
              clear(`${prefix}-${r.key}`);
            }}
          />
          <Button type="button" variant="ghost" size="icon-touch" aria-label={`Quitar ${label.toLowerCase()} ${i + 1}`} onClick={() => set(rows.filter((x) => x.key !== r.key))}>
            <XIcon />
          </Button>
        </div>
        <FieldError>{errors[`${prefix}-${r.key}`]}</FieldError>
      </Field>
    ));

  const addButton = (label: string, onClick: () => void) => (
    <Button type="button" variant="outline" size="touch" className="w-full border-dashed font-bold text-primary" onClick={onClick}>
      <PlusIcon />
      {label}
    </Button>
  );

  return (
    <form noValidate onSubmit={submit} className="flex flex-1 flex-col gap-4 px-4 pb-4">
      <Card className="text-base">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Datos</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field {...fieldProps("name")}>
              <FieldLabel htmlFor="pname">Nombre</FieldLabel>
              <Input
                id="pname"
                placeholder="Nombre y apellido"
                className="h-12 text-base"
                autoComplete="off"
                value={name}
                {...inputProps("name")}
                onChange={(e) => {
                  setName(e.target.value);
                  clear("name");
                }}
              />
              <FieldError>{errors.name}</FieldError>
            </Field>
            <Field>
              <FieldLabel htmlFor="pphone">Celular del paciente (opcional)</FieldLabel>
              <PhoneInput
                id="pphone"
                value={phone}
                onChange={setPhone}
                autoComplete="off"
                placeholder="099 123 456"
                numberInputProps={{ className: "h-12 text-base" }}
              />
              <FieldDescription>Si el paciente se registra con este número, entra directo a su perfil, sin invitación.</FieldDescription>
            </Field>
            <Field {...fieldProps("location")}>
              <FieldLabel htmlFor="room">Habitación o domicilio</FieldLabel>
              <Input
                id="room"
                placeholder="Hab. 12"
                className="h-12 text-base"
                autoComplete="off"
                value={location}
                {...inputProps("location")}
                onChange={(e) => {
                  setLocation(e.target.value);
                  clear("location");
                }}
              />
              <FieldError>{errors.location}</FieldError>
            </Field>
            <FieldSet>
              <FieldLegend variant="label">Número de emergencia (opcional)</FieldLegend>
              <FieldDescription>Es el número que la app ofrece llamar si hay una emergencia. Sin número, ofrece el 911.</FieldDescription>
              <Field {...fieldProps("ecName")}>
                <FieldLabel htmlFor="ecname">Nombre</FieldLabel>
                <Input
                  id="ecname"
                  placeholder="Emergencias Residencia"
                  className="h-12 text-base"
                  autoComplete="off"
                  value={ecName}
                  {...inputProps("ecName")}
                  onChange={(e) => {
                    setEcName(e.target.value);
                    clear("ecName");
                  }}
                />
                <FieldError>{errors.ecName}</FieldError>
              </Field>
              <Field {...fieldProps("ecPhone")}>
                <FieldLabel htmlFor="ecphone">Teléfono</FieldLabel>
                <Input
                  id="ecphone"
                  type="tel"
                  inputMode="tel"
                  placeholder="+598 99 123 456"
                  className="h-12 text-base"
                  autoComplete="off"
                  value={ecPhone}
                  {...inputProps("ecPhone")}
                  onChange={(e) => {
                    setEcPhone(e.target.value);
                    clear("ecPhone");
                  }}
                />
                <FieldError>{errors.ecPhone}</FieldError>
              </Field>
            </FieldSet>
          </FieldGroup>
        </CardContent>
      </Card>

      <Card className="text-base">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Plan de cuidado</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <FieldSet>
            <FieldLegend>Medicación</FieldLegend>
            <div className="flex flex-col gap-3">
              {meds.map((m, i) => {
                const set = (patch: Partial<MedRow>) => setMeds(meds.map((x) => (x.key === m.key ? { ...x, ...patch } : x)));
                return (
                  <Item key={m.key} variant="muted" className="items-start rounded-xl">
                    <ItemContent>
                      <FieldGroup className="gap-3">
                        <Field {...fieldProps(`med-${m.key}-name`)}>
                          <FieldLabel htmlFor={`med-${m.key}-name`}>Nombre</FieldLabel>
                          <Input id={`med-${m.key}-name`} placeholder="Ej.: Enalapril" className="h-12 bg-card text-base" value={m.name} {...inputProps(`med-${m.key}-name`)}
                            onChange={(e) => { set({ name: e.target.value }); clear(`med-${m.key}-name`); }} />
                          <FieldError>{errors[`med-${m.key}-name`]}</FieldError>
                        </Field>
                        <Field {...fieldProps(`med-${m.key}-dose`)}>
                          <FieldLabel htmlFor={`med-${m.key}-dose`}>Dosis, tal como está indicada</FieldLabel>
                          <Input id={`med-${m.key}-dose`} placeholder="Ej.: 1 comprimido" className="h-12 bg-card text-base" value={m.dose} {...inputProps(`med-${m.key}-dose`)}
                            onChange={(e) => { set({ dose: e.target.value }); clear(`med-${m.key}-dose`); }} />
                          <FieldError>{errors[`med-${m.key}-dose`]}</FieldError>
                        </Field>
                        <Field {...fieldProps(`med-${m.key}-times`)}>
                          <FieldLabel htmlFor={`med-${m.key}-times`}>Horarios</FieldLabel>
                          <Input id={`med-${m.key}-times`} placeholder="08:00, 20:00" inputMode="numeric" className="h-12 bg-card text-base" value={m.times} {...inputProps(`med-${m.key}-times`)}
                            onChange={(e) => { set({ times: e.target.value }); clear(`med-${m.key}-times`); }} />
                          {errors[`med-${m.key}-times`] ? <FieldError>{errors[`med-${m.key}-times`]}</FieldError> : <FieldDescription>Separados por coma. Vacío si no tiene horario fijo.</FieldDescription>}
                        </Field>
                      </FieldGroup>
                    </ItemContent>
                    <ItemActions>
                      <Button type="button" variant="ghost" size="icon-touch" aria-label={`Quitar medicación ${i + 1}`} onClick={() => setMeds(meds.filter((x) => x.key !== m.key))}>
                        <XIcon />
                      </Button>
                    </ItemActions>
                  </Item>
                );
              })}
              {addButton("Medicación", () => setMeds([...meds, { key: key(), name: "", dose: "", times: "" }]))}
            </div>
          </FieldSet>
          <FieldSet>
            <FieldLegend>Indicaciones</FieldLegend>
            <div className="flex flex-col gap-3">
              {textList(indications, setIndications, "ind", "Indicación", "Ej.: Ofrecer agua seguido")}
              {addButton("Indicación", () => setIndications([...indications, { key: key(), text: "" }]))}
            </div>
          </FieldSet>
          <FieldSet>
            <FieldLegend>Alergias</FieldLegend>
            <div className="flex flex-col gap-3">
              {textList(allergies, setAllergies, "all", "Alergia", "Ej.: Penicilina")}
              {addButton("Alergia", () => setAllergies([...allergies, { key: key(), text: "" }]))}
            </div>
          </FieldSet>
          <FieldDescription>Se carga tal como lo indicó el médico. CercanIA no calcula ni sugiere dosis.</FieldDescription>
        </CardContent>
      </Card>

      <Card className="text-base">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Equipo y accesos</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <TeamList
            rows={[
              { key: "me", name: "Vos", role: "caregiver" },
              ...invites.map((inv) => ({
                key: inv.phone,
                name: inv.phone,
                role: inv.role,
                pending: saved ? undefined : "Se invita al guardar",
                onRemove: saved ? undefined : () => setInvites(invites.filter((x) => x.phone !== inv.phone)),
              })),
            ]}
          />
          {!saved && (
            <InviteForm
              title="Invitar a un familiar"
              submitLabel="Agregar invitación"
              roles={["family"]}
              onInvite={(phone, role) => {
                if (phone === patientPhone) return "Ese es el celular del paciente: ya entra directo con ese número.";
                if (invites.some((x) => x.phone === phone)) return "Ese número ya está en la lista.";
                setInvites([...invites, { phone, role }]);
                return null;
              }}
            />
          )}
          <FieldDescription>
            Familia: solo lectura; entra con su número de celular y acepta la invitación en la app. El paciente entra con el celular cargado arriba. El equipo de salud lo asigna una persona administradora.
          </FieldDescription>
        </CardContent>
      </Card>

      {saved && (
        <Alert variant="warning" role="alert">
          <AlertTitle>Paciente guardado, pero faltan invitaciones</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {saved.inviteErrors.map((x) => (
                <li key={x.contact}>
                  {x.contact}: {x.error.message}
                </li>
              ))}
            </ul>
            Podés volver a invitarlos desde el equipo del paciente.
          </AlertDescription>
        </Alert>
      )}
      {formError && !saved && (
        <Alert variant="danger-soft" role="alert">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}

      {saved ? (
        <div className="flex flex-col gap-2">
          <Button asChild size="xl">
            <Link href={`/patients/${saved.patientId}/team` as Route}>Ir al equipo</Link>
          </Button>
          <Button asChild variant="outline" size="touch">
            <Link href={`/patients/${saved.patientId}` as Route}>Ir al paciente</Link>
          </Button>
        </div>
      ) : (
        <Button type="submit" size="xl" disabled={saving}>
          {saving && <Spinner />}
          {saving ? "Guardando…" : "Guardar paciente"}
        </Button>
      )}
    </form>
  );
}
