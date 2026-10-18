// My patients (artboard "Patients"). Ticket: CIA-33.
import Link from "next/link";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { MailPlusIcon, PlusIcon, UsersRoundIcon } from "lucide-react";
import { AppShell, BottomBar, Brand } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { getMe, getMyInvites, getMyPatients } from "@/lib/api";
import { PatientList } from "./patient-list";
import { PendingInvites } from "./pending-invites";

export default async function PatientsPage() {
  const [patients, invites, me] = await Promise.all([getMyPatients(), getMyInvites(), getMe()]);
  // A patient's only screen is their own view (CIA-35): no list, no other navigation.
  if (patients.length === 1 && patients[0].role === "patient" && invites.length === 0) redirect(`/patients/${patients[0].id}/me` as Route);
  // Red flags first, then by open alerts, then missing reports.
  const sorted = [...patients].sort(
    (a, b) =>
      Number(b.red_flag ?? false) - Number(a.red_flag ?? false) ||
      (b.open_alerts ?? 0) - (a.open_alerts ?? 0) ||
      Number(b.missing_report ?? false) - Number(a.missing_report ?? false),
  );

  // Only caregivers add patients (CIA-48), including one an admin registered before assigning any.
  const canAdd = me.can_add_patients;

  return (
    <AppShell>
      <header className="px-5 pt-5 pb-3">
        <Brand />
      </header>
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <h1 className="text-[28px] font-bold">Mis pacientes</h1>
        {me.is_admin && (
          <Button asChild variant="outline" size="touch" className="self-start">
            <Link href="/admin">
              <UsersRoundIcon />
              Usuarios y roles
            </Link>
          </Button>
        )}

        <PendingInvites invites={invites} />
        <PatientList
          patients={sorted}
          hideEmpty={invites.length > 0}
          empty={
            canAdd
              ? { title: "Todavía no tenés pacientes asignados", description: "Agregá uno, o esperá a que una persona administradora te asigne." }
              : undefined
          }
        />

        {canAdd && (
          <Button asChild variant="outline" size="touch">
            <Link href="/patients/invite">
              <MailPlusIcon />
              Invitar a un paciente
            </Link>
          </Button>
        )}

        <p className="px-1 text-[13px] text-muted-foreground">Enfermería y médicos ven esta misma lista con sus pacientes asignados.</p>
      </main>
      {canAdd && (
        <BottomBar>
          <Button asChild size="xl">
            <Link href="/patients/new">
              <PlusIcon />
              Agregar paciente
            </Link>
          </Button>
        </BottomBar>
      )}
    </AppShell>
  );
}
