// New report from the web (artboard "NewReport"). Ticket: CIA-31.
// Skeleton: recording (MediaRecorder) and sending to POST /patients/{id}/reports land in CIA-31.
import { MessageCircleIcon, MicIcon } from "lucide-react";
import { AppShell, BottomBar, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        <Card className="text-base">
          <CardContent className="flex flex-col items-center gap-3 py-2">
            <Button
              variant="danger"
              aria-label="Empezar a grabar"
              className="size-28 rounded-full border-8 border-danger-ring [&_svg]:size-9!"
            >
              <MicIcon />
            </Button>
            <span className="font-heading text-[28px] font-bold">0:00</span>
            <p className="text-center text-sm text-muted-foreground">Tocá para grabar. Contá cómo fue el turno con tus palabras.</p>
            <Button variant="outline" size="touch" className="font-bold">
              Prefiero escribirlo
            </Button>
          </CardContent>
        </Card>

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
            Es el mismo reporte que mandás por WhatsApp. Al enviarlo te respondemos “Registré: …” para que lo confirmes.
          </AlertDescription>
        </Alert>
      </main>
      <BottomBar>
        <Button size="xl" disabled>
          Enviar reporte
        </Button>
      </BottomBar>
    </AppShell>
  );
}
