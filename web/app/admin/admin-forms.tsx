"use client";
// Admin forms (CIA-48, CIA-58): pre-register a phone, set a person's role, delete a pending pre-registration.
// An admin sets roles only, never links people to patients. Every change that would replace something
// opens a confirmation with what exists now.

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
  setRoleAction,
} from "./actions";
import { ADMIN_ROLE_LABEL } from "./labels";

const PERSON_ROLES: Role[] = ["caregiver", "family", "doctor", "nurse", "institution", "patient"];
const PRE_ROLES: AdminRole[] = [...PERSON_ROLES, "admin"];

function roleText(person: AdminPerson): string {
  const parts = [person.role ? ADMIN_ROLE_LABEL[person.role].toLowerCase() : "sin rol"];
  if (person.is_admin) parts.unshift("administración");
  return parts.join(", ");
}

/** "Este usuario ya existe: Ana, cuidador/a." from a 409's current state. */
export function describeCurrent(current: OverwriteCurrent): string {
  if ("pre_registration" in current) {
    const p = current.pre_registration;
    return `Ese número ya tiene un rol pendiente de registro: ${ADMIN_ROLE_LABEL[p.role].toLowerCase()}.`;
  }
  const person = "person" in current ? current.person : current;
  return `Este usuario ya existe: ${person.name}, ${roleText(person)}.`;
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
              // Something changed since the warning (e.g. the phone signed up): ask again with what is there now.
              if ("conflict" in res) setAsk({ text: describeCurrent(res.conflict.current), retry });
              else if ("error" in res) toast.error(res.error);
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

const MAKE_ADMIN = {
  title: "¿Hacer administrador/a?",
  note: "Va a poder ver la lista de usuarios y elegir sus roles. Su rol no cambia.",
  action: "Sí, hacer administrador/a",
  done: "Ahora es administrador/a.",
};

export function PreRegisterForm() {
  const id = useId();
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<AdminRole>("caregiver");
  const [error, setError] = useState<string | null>(null);
  // Making a registered person admin keeps their roles: say so instead of "reemplaza".
  const { pending, run, dialog } = useConfirmed(role === "admin" ? MAKE_ADMIN : REPLACE);

  async function submit() {
    const err = await run(
      () => preRegisterAction(phone, role),
      () => preRegisterAction(phone, role, true),
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
      <Button type="button" size="touch" className="w-full" disabled={pending || !phone.trim()} onClick={() => void submit()}>
        {pending && <Spinner />}
        Guardar rol pendiente
      </Button>
      {dialog}
    </FieldGroup>
  );
}

const LEAVES_PATIENT = " Deja de entrar a su perfil de paciente; el perfil y sus registros quedan guardados.";

/** The admin sets the person's role (CIA-58). Never links them to a patient. */
export function PersonRole({ person }: { person: AdminPerson }) {
  const [role, setRole] = useState<Role | "">(person.role ?? "");
  const [error, setError] = useState<string | null>(null);
  const leavesPatient = person.role === "patient" && role !== "patient";
  const { pending, run, dialog } = useConfirmed(leavesPatient ? { ...REPLACE, note: REPLACE.note + LEAVES_PATIENT } : REPLACE);

  async function submit() {
    if (!role) return;
    const err = await run(
      () => setRoleAction(person.id, role),
      () => setRoleAction(person.id, role, true),
      `Rol guardado para ${person.name}.`,
    );
    setError(err);
  }

  return (
    <div className="flex flex-col gap-2">
      <Select value={role || undefined} onValueChange={(v) => { setRole(v as Role); setError(null); }}>
        <SelectTrigger aria-label={`Rol de ${person.name}`} className="h-12! w-full bg-card text-base">
          <SelectValue placeholder="Sin rol" />
        </SelectTrigger>
        <SelectContent>
          {PERSON_ROLES.map((r) => (
            <SelectItem key={r} value={r}>
              {ADMIN_ROLE_LABEL[r]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && <p className="text-[13px] text-destructive">{error}</p>}
      <Button
        type="button"
        variant="outline-primary"
        size="touch"
        disabled={pending || !role || role === person.role}
        onClick={() => void submit()}
      >
        {pending && <Spinner />}
        Guardar rol
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
