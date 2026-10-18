// Invite a patient who has no profile yet (CIA-48). Caregivers only; when the person accepts in the app,
// their patient profile is created and the inviting caregiver becomes its caregiver.
import { AppShell, TopBar } from "@/components/app/shell";
import { InvitePatient } from "./invite-patient";

export default function InvitePatientPage() {
  return (
    <AppShell>
      <TopBar back="/patients" title="Invitar a un paciente" subtitle="Se registra con su celular y queda a tu cargo" />
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <InvitePatient />
        <p className="px-1 text-[13px] text-muted-foreground">
          Si el paciente ya está en tu lista, invitalo desde su pantalla de equipo para darle su propio acceso.
        </p>
      </main>
    </AppShell>
  );
}
