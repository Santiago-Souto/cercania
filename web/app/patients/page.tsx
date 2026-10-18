// My patients (artboard "Patients"). Ticket: CIA-33.
import Link from "next/link";
import { PlusIcon } from "lucide-react";
import { AppShell, BottomBar, Brand } from "@/components/app/shell";
import { Button } from "@/components/ui/button";
import { getMyPatients } from "@/lib/api";
import type { Role } from "@/lib/types";
import { PatientList } from "./patient-list";

const ADDERS = new Set<Role>(["caregiver", "doctor", "nurse", "institution"]);

export default async function PatientsPage() {
  const patients = await getMyPatients();
  // Red flags first, then by open alerts, then missing reports.
  const sorted = [...patients].sort(
    (a, b) =>
      Number(b.red_flag ?? false) - Number(a.red_flag ?? false) ||
      (b.open_alerts ?? 0) - (a.open_alerts ?? 0) ||
      Number(b.missing_report ?? false) - Number(a.missing_report ?? false),
  );

  // Caregivers and the health team add patients; a new user with no patients yet must be able to start.
  const canAdd = patients.length === 0 || patients.some((p) => ADDERS.has(p.role));

  return (
    <AppShell>
      <header className="px-5 pt-5 pb-3">
        <Brand />
      </header>
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <h1 className="text-[28px] font-bold">Mis pacientes</h1>

        <PatientList patients={sorted} />

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
