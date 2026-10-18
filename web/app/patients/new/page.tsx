// Add patient + team roles (artboard "AddPatient"). Ticket: CIA-34.
// POST /patients, then POST /patients/{id}/invites per queued invite (app/patients/actions.ts).
import { AppShell, TopBar } from "@/components/app/shell";
import { NewPatientForm } from "./new-patient-form";

export default function AddPatientPage() {
  return (
    <AppShell>
      <TopBar back="/patients" title="Nuevo paciente" />
      <NewPatientForm />
    </AppShell>
  );
}
