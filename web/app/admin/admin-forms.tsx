"use client";
// Admin forms (CIA-48): pre-register a phone, assign / remove a role, delete a pending pre-registration.
// Every change that would replace something opens a confirmation with what exists now.

import { useId, useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import type { AdminPerson, AdminPreRegistration, AdminRole, OverwriteCurrent, Role } from "@/lib/types";
import {
  type AdminResult,
  deletePreRegistrationAction,
  makeAdminAction,
  preRegisterAction,
  removeMembershipAction,
  setMembershipAction,
} from "./actions";
import { ADMIN_ROLE_LABEL } from "./labels";

type PatientOption = { id: string; display_name: string };

const MEMBER_ROLES: Role[] = ["caregiver", "family", "doctor", "nurse", "institution", "patient"];
const PRE_ROLES: AdminRole[] = ["caregiver", "family", "doctor", "nurse", "institution", "patient", "admin"];
// Same rules as the backend (app/roles.py).
const NEEDS_PATIENT = new Set<AdminRole>(["family", "doctor", "nurse", "institution"]);
const NO_PATIENT = new Set<AdminRole>(["admin", "patient"]);
const NONE = "__none__";

function roleList(person: AdminPerson): string {
  const parts = person.memberships.map((m) => `${ADMIN_ROLE_LABEL[m.role].toLowerCase()} de ${m.patient_name}`);
  if (person.is_caregiver && !person.memberships.some((m) => m.role === "caregiver")) parts.push("cuidador/a sin pacientes");
  if (person.is_admin) parts.unshift("administración");
  return parts.length ? parts.join(", ") : "sin roles";
}

/** "Este usuario ya existe: Ana, cuidador/a de Rosa." from a 409's current state. */
export function describeCurrent(current: OverwriteCurrent): string {
  if ("pre_registration" in current) {
    const p = current.pre_registration;
    return `Ese número ya tiene un rol pendiente de registro: ${ADMIN_ROLE_LABEL[p.role].toLowerCase()}${p.patient_name ? ` de ${p.patient_name}` : ""}.`;
  }
  const person = "person" in current ? current.person : current;
  return `Este usuario ya existe: ${person.name}, ${roleList(person)}.`;
}

const REPLACE = { title: "¿Reemplazar?", note: "Si confirmás, el rol nuevo reemplaza al actual.", action: "Sí, reemplazar", done: "Rol reemplazado." };

/** Runs an action; on a 409 asks for confirmation and re-runs it with confirm=true. */
function useConfirmed(copy = REPLACE) {
  const [pending, setPending] = useState(false);
  const [ask, setAsk] = useState<{ text: string; retry: () => Promise<AdminResult> } | null>(null);

  async function run(first: () => Promise<AdminResult>, retry: () => Promise<AdminResult>, done: string): Promise<string | null> {
    setPending(true);
    try {
      const res = await first();
      if ("conflict" in res) {
        setAsk({ text: describeCurrent(res.conflict.current), retry });
        return null;
      }
      if ("error" in res) return res.error;
      toast.success(done);
      return null;
    } catch {
      return "No pudimos guardar el cambio. Revisá tu conexión y probá de nuevo.";
    } finally {
      setPending(false);
    }
  }

  const dialog = (
    <AlertDialog open={!!ask} onOpenChange={(open) => !open && setAsk(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>
            {ask?.text} {copy.note}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>No, dejarlo como está</AlertDialogCancel>
          <AlertDialogAction
            onClick={async () => {
              const retry = ask?.retry;
              setAsk(null);
              if (!retry) return;
              const res = await retry();
              if ("error" in res) toast.error(res.error);
              else toast.success(copy.done);
            }}
          >
            {copy.action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
  return { pending, run, dialog };
}

function PatientSelect({ id, value, onChange, patients, optional }: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  patients: PatientOption[];
  optional?: boolean;
}) {
  return (
    <Select value={value || (optional ? NONE : undefined)} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
      <SelectTrigger id={id} className="h-12! w-full bg-card text-base">
        <SelectValue placeholder="Elegí el paciente" />
      </SelectTrigger>
      <SelectContent>
        {optional && <SelectItem value={NONE}>Sin paciente por ahora</SelectItem>}
        {patients.map((p) => (
          <SelectItem key={p.id} value={p.id}>
            {p.display_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const MAKE_ADMIN = {
  title: "¿Hacer administrador/a?",
  note: "Va a poder ver la lista de usuarios y asignar roles. Sus roles con pacientes no cambian.",
  action: "Sí, hacer administrador/a",
  done: "Ahora es administrador/a.",
};

export function PreRegisterForm({ patients }: { patients: PatientOption[] }) {
  const id = useId();
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<AdminRole>("caregiver");
  const [patientId, setPatientId] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Making a registered person admin keeps their roles: say so instead of "reemplaza".
  const { pending, run, dialog } = useConfirmed(role === "admin" ? MAKE_ADMIN : REPLACE);
  const showPatient = !NO_PATIENT.has(role);

  async function submit() {
    if (NEEDS_PATIENT.has(role) && !patientId) return setError("Elegí el paciente para este rol.");
    const patient = showPatient && patientId ? patientId : null;
    const err = await run(
      () => preRegisterAction(phone, role, patient),
      () => preRegisterAction(phone, role, patient, true),
      "Guardado. Cuando esa persona se registre con ese número, entra con este rol.",
    );
    setError(err);
    if (!err) setPhone("");
  }

  return (
    <FieldGroup className="gap-3">
      <Field data-invalid={!!error || undefined}>
        <FieldLabel htmlFor={`${id}-phone`}>Celular</FieldLabel>
        <Input
          id={`${id}-phone`}
          type="tel"
          inputMode="tel"
          autoComplete="off"
          placeholder="+598 9X XXX XXX"
          className="h-12 bg-card text-base"
          value={phone}
          onChange={(e) => {
            setPhone(e.target.value);
            setError(null);
          }}
        />
        {error ? <FieldError>{error}</FieldError> : <FieldDescription>No se le manda nada: se registra por su cuenta y entra con este rol.</FieldDescription>}
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}-role`}>Rol</FieldLabel>
        <Select value={role} onValueChange={(v) => setRole(v as AdminRole)}>
          <SelectTrigger id={`${id}-role`} className="h-12! w-full bg-card text-base">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRE_ROLES.map((r) => (
              <SelectItem key={r} value={r}>
                {ADMIN_ROLE_LABEL[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {role === "patient" && <FieldDescription>Al registrarse se le crea su propio perfil de paciente.</FieldDescription>}
      </Field>
      {showPatient && (
        <Field>
          <FieldLabel htmlFor={`${id}-patient`}>Paciente{role === "caregiver" ? " (opcional)" : ""}</FieldLabel>
          <PatientSelect id={`${id}-patient`} value={patientId} onChange={setPatientId} patients={patients} optional={role === "caregiver"} />
        </Field>
      )}
      <Button type="button" size="touch" className="w-full" disabled={pending || !phone.trim()} onClick={() => void submit()}>
        {pending && <Spinner />}
        Guardar rol pendiente
      </Button>
      {dialog}
    </FieldGroup>
  );
}

export function AssignRole({ person, patients }: { person: AdminPerson; patients: PatientOption[] }) {
  const id = useId();
  const [patientId, setPatientId] = useState("");
  const [role, setRole] = useState<Role>("caregiver");
  const [error, setError] = useState<string | null>(null);
  const { pending, run, dialog } = useConfirmed();

  async function submit() {
    if (!patientId) return setError("Elegí el paciente.");
    const err = await run(
      () => setMembershipAction(person.id, patientId, role),
      () => setMembershipAction(person.id, patientId, role, true),
      `Rol asignado a ${person.name}.`,
    );
    setError(err);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <PatientSelect id={`${id}-patient`} value={patientId} onChange={(v) => { setPatientId(v); setError(null); }} patients={patients} />
        <Select value={role} onValueChange={(v) => setRole(v as Role)}>
          <SelectTrigger aria-label="Rol" className="h-12! w-full bg-card text-base">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MEMBER_ROLES.map((r) => (
              <SelectItem key={r} value={r}>
                {ADMIN_ROLE_LABEL[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {error && <p className="text-[13px] text-destructive">{error}</p>}
      <Button type="button" variant="outline-primary" size="touch" disabled={pending} onClick={() => void submit()}>
        {pending && <Spinner />}
        Asignar rol
      </Button>
      {dialog}
    </div>
  );
}


/** Another admin makes an existing person admin (CIA-48); the backend asks for confirmation first. */
export function MakeAdmin({ person }: { person: AdminPerson }) {
  const { pending, run, dialog } = useConfirmed(MAKE_ADMIN);
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="touch"
        disabled={pending}
        onClick={async () => {
          const err = await run(() => makeAdminAction(person.id), () => makeAdminAction(person.id, true), MAKE_ADMIN.done);
          if (err) toast.error(err);
        }}
      >
        {pending && <Spinner />}
        Hacer administrador/a
      </Button>
      {dialog}
    </>
  );
}

export function RemoveRole({ person, patientId, label }: { person: AdminPerson; patientId: string; label: string }) {
  const [pending, setPending] = useState(false);
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button type="button" variant="ghost" size="sm" disabled={pending} aria-label={`Quitar: ${label}`}>
          {pending ? <Spinner /> : "Quitar"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>¿Quitar este rol?</AlertDialogTitle>
          <AlertDialogDescription>
            {person.name} deja de ser {label} y pierde el acceso a ese paciente.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>No</AlertDialogCancel>
          <AlertDialogAction
            variant="danger"
            onClick={async () => {
              setPending(true);
              const res = await removeMembershipAction(person.id, patientId).catch(
                () => ({ error: "No pudimos quitar el rol. Probá de nuevo." }) as AdminResult,
              );
              setPending(false);
              if ("error" in res) toast.error(res.error);
              else toast.success("Rol quitado.");
            }}
          >
            Sí, quitar
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function DeletePreRegistration({ pre }: { pre: AdminPreRegistration }) {
  const [pending, setPending] = useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={pending}
      onClick={async () => {
        setPending(true);
        const res = await deletePreRegistrationAction(pre.id).catch(() => ({ error: "No pudimos borrarlo." }) as AdminResult);
        setPending(false);
        if ("error" in res) toast.error(res.error);
        else toast.success("Rol pendiente borrado.");
      }}
    >
      {pending && <Spinner />}
      Borrar
    </Button>
  );
}
