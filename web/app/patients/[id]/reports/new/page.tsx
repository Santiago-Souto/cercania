// New report from the web (artboard "NewReport"). Ticket: CIA-31.
// Text goes to POST /patients/{id}/reports; recording (MediaRecorder) lands in CIA-31.
import { MessageCircleIcon } from "lucide-react";
import { ReportForm } from "@/components/app/report-form";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { getPatient } from "@/lib/api";
import { CHECKLIST_LABEL } from "@/lib/format";
import type { ChecklistItem } from "@/lib/types";

const ITEMS = Object.keys(CHECKLIST_LABEL) as ChecklistItem[];

export default async function NewReportPage(props: PageProps<"/patients/[id]/reports/new">) {
  const { id } = await props.params;
  const patient = await getPatient(id);

  return (
    <AppShell>
      <TopBar back={`/patients/${id}`} title="Nuevo reporte" subtitle={`${patient.display_name} · fin de turno`} />
      <ReportForm patientId={id} />
      <aside className="flex flex-col gap-4 px-4 pb-4">
        <section className="flex flex-col gap-2.5">
          <h2 className="font-sans text-[13px] font-bold tracking-wide text-muted-foreground uppercase">Acordate de contar</h2>
          <div className="grid grid-cols-2 gap-2">
            {ITEMS.map((i) => (
              <Badge key={i} variant="outline" className="h-11 w-full justify-start rounded-xl bg-card px-3 text-sm font-normal">
                {CHECKLIST_LABEL[i]}
              </Badge>
            ))}
          </div>
          <p className="text-[13px] text-muted-foreground">Si te olvidás de algo, te lo preguntamos después.</p>
        </section>

        <Alert className="rounded-xl border-0 bg-secondary p-3.5 text-primary">
          <MessageCircleIcon />
          <AlertDescription className="text-sm text-primary">
            Es el mismo reporte que mandás por WhatsApp. Al enviarlo te respondemos “Registré: …” con lo que quedó guardado.
          </AlertDescription>
        </Alert>
      </aside>
    </AppShell>
  );
}
