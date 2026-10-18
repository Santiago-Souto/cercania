// Family <-> health team messages (artboard "Messages"). Ticket: CIA-36 (bonus). Human-to-human, no model.
import { TriangleAlertIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { getMessages, getMyPatients, getPatient } from "@/lib/api";
import { MessageThread } from "./thread";

export default async function MessagesPage(props: PageProps<"/patients/[id]/messages">) {
  const { id } = await props.params;
  const [patient, messages, mine] = await Promise.all([getPatient(id), getMessages(id), getMyPatients()]);
  const role = mine.find((p) => p.id === id)?.role;

  return (
    <AppShell>
      <TopBar
        back={role === "family" ? `/patients/${id}/family` : `/patients/${id}`}
        title={role === "family" ? "Equipo de salud" : "Mensajes de la familia"}
        subtitle={`Sobre ${patient.display_name}`}
      />
      <div className="px-4 pb-3">
        <Alert variant="warning">
          <TriangleAlertIcon />
          <AlertDescription className="text-[13px]">No es para urgencias. Ante una urgencia, llamá a emergencias.</AlertDescription>
        </Alert>
      </div>
      <MessageThread patientId={id} initial={messages} />
    </AppShell>
  );
}
