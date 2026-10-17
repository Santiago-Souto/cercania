// Patient's own view (artboard "Patient"). Ticket: CIA-35.
// Only two actions. "Necesito ayuda" is a fixed rule in the backend (AGENTS.md §7); wiring lands in CIA-35/CIA-29.
import { CheckIcon, MicIcon, TriangleAlertIcon } from "lucide-react";
import { AppShell } from "@/components/app/shell";
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
import { Card, CardContent, CardDescription } from "@/components/ui/card";
import { getPatient, getPatientMessages } from "@/lib/api";
import { dayTime, firstName } from "@/lib/format";

export default async function PatientSelfPage(props: PageProps<"/patients/[id]/me">) {
  const { id } = await props.params;
  const [patient, messages] = await Promise.all([getPatient(id), getPatientMessages(id)]);
  const last = messages[0];

  return (
    <AppShell>
      <main className="flex flex-1 flex-col gap-5 px-5 pt-8 pb-7 text-[19px]">
        <section className="flex flex-col gap-1">
          <h1 className="text-[34px] leading-tight font-bold">Hola, {firstName(patient.display_name)}</h1>
          <p className="text-ink-2">¿Cómo te sentís hoy?</p>
        </section>

        <Button className="h-auto min-h-56 flex-col gap-3 rounded-[28px] py-6 whitespace-normal">
          <span className="flex size-22 items-center justify-center rounded-full bg-card text-primary">
            <MicIcon className="size-10!" />
          </span>
          <span className="font-heading text-2xl font-bold">Contar cómo me siento</span>
          <span className="text-base font-normal">Tocá y hablá</span>
        </Button>

        <Button variant="outline-primary" className="h-16 rounded-2xl text-[19px] font-bold">
          Prefiero escribir
        </Button>

        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="danger" className="h-22 rounded-3xl font-heading text-2xl font-bold [&_svg]:size-8!">
              <TriangleAlertIcon />
              Necesito ayuda
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="text-2xl">¿Avisamos a tu equipo?</AlertDialogTitle>
              <AlertDialogDescription className="text-lg">
                Les llega un mensaje ahora mismo. Si es una emergencia, llamá a emergencias.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="h-14 text-lg">No, volver</AlertDialogCancel>
              <AlertDialogAction className="h-14 bg-danger text-lg text-danger-foreground hover:bg-danger/90">
                Sí, pedir ayuda
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {last && (
          <Card className="gap-1 text-base">
            <CardContent className="flex flex-col gap-1">
              <CardDescription className="text-base">Tu último mensaje · {dayTime(last.created_at).toLowerCase()}</CardDescription>
              {last.text && <em>“{last.text}”</em>}
              {last.seen_by.length > 0 && (
                <span className="flex items-center gap-1 font-bold text-primary">
                  Lo vio {last.seen_by.map((p) => p.name).join(", ")} <CheckIcon className="size-4" />
                </span>
              )}
            </CardContent>
          </Card>
        )}
      </main>
    </AppShell>
  );
}
