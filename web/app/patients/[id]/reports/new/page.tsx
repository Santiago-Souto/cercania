// New report from the web (artboard "NewReport"). Ticket: CIA-31.
// Same report as WhatsApp: recorded or typed in ReportComposer, sent to POST /patients/{id}/reports.
import { MessageCircleIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { getPatient } from "@/lib/api";
import { ReportComposer } from "./report-composer";

export default async function NewReportPage(props: PageProps<"/patients/[id]/reports/new">) {
  const { id } = await props.params;
  const patient = await getPatient(id);

  return (
    <AppShell>
      <TopBar back={`/patients/${id}`} title="Nuevo reporte" subtitle={`${patient.display_name} · fin de turno`} />
      <ReportComposer patientId={id}>
        <Alert className="rounded-xl border-0 bg-secondary p-3.5 text-primary">
          <MessageCircleIcon />
          <AlertDescription className="text-sm text-primary">
            Es el mismo reporte que mandás por WhatsApp. Al enviarlo te respondemos “Registré: …” con lo que quedó anotado.
          </AlertDescription>
        </Alert>
      </ReportComposer>
    </AppShell>
  );
}
