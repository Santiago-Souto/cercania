// Patient's own view (artboard "Patient"). Ticket: CIA-35.
// Only two actions, no other navigation: tell how I feel and "Necesito ayuda" (AGENTS.md §6),
// plus any pending invite to their phone (this is a patient's only screen).
// Open to the patient role, and to caregivers testing it (they also hold `send_patient_message`).
import { redirect } from "next/navigation";
import type { Route } from "next";
import { CheckIcon } from "lucide-react";
import { AppShell } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { getMyInvites, getMyPatients, getPatient, getPatientMessages } from "@/lib/api";
import { dayTime, firstName } from "@/lib/format";
import { PendingInvites } from "../../pending-invites";
import { PatientActions } from "./patient-actions";

const SHOWN_MESSAGES = 10;

export default async function PatientSelfPage(props: PageProps<"/patients/[id]/me">) {
  const { id } = await props.params;
  const mine = await getMyPatients();
  const role = mine.find((p) => p.id === id)?.role;
  // Family and health team see the patient's messages from their own screens; this one is for the patient.
  if (role && role !== "patient" && role !== "caregiver") redirect(`/patients/${id}` as Route);

  const [patient, messages, invites] = await Promise.all([getPatient(id), getPatientMessages(id), getMyInvites()]);
  const shown = messages.slice(0, SHOWN_MESSAGES);

  return (
    <AppShell>
      <main className="flex flex-1 flex-col gap-5 px-5 pt-8 pb-7 text-[19px]">
        <section className="flex flex-col gap-1">
          <h1 className="text-[34px] leading-tight font-bold">Hola, {firstName(patient.display_name)}</h1>
          <p className="text-ink-2">¿Cómo te sentís hoy?</p>
        </section>

        {/* A caregiver's invite (e.g. to be the login of a profile they already keep) shows here too. */}
        <PendingInvites invites={invites} />

        <PatientActions patientId={id} />

        {shown.length > 0 && (
          <section className="flex flex-col gap-2.5">
            <h2 className="font-sans text-sm font-bold tracking-wide text-muted-foreground uppercase">Tus mensajes</h2>
            <ItemGroup className="gap-2.5">
              {shown.map((m, i) => (
                <Item key={m.id} variant="outline" className="rounded-xl bg-card px-4 py-3">
                  <ItemContent className="gap-1">
                    <ItemDescription className="text-base">
                      {i === 0 ? "Tu último mensaje" : "Mensaje"} · {dayTime(m.created_at).toLowerCase()}
                    </ItemDescription>
                    <ItemTitle className="text-[19px] font-normal">
                      {m.kind === "help" ? (
                        <Badge variant="danger" className="text-base">
                          Pediste ayuda
                        </Badge>
                      ) : (
                        <em>“{m.text}”</em>
                      )}
                    </ItemTitle>
                    {m.seen_by.length > 0 ? (
                      <span className="flex items-center gap-1 text-base font-bold text-primary">
                        Lo vio {m.seen_by.map((p) => p.name).join(", ")} <CheckIcon className="size-4" aria-hidden="true" />
                      </span>
                    ) : (
                      <span className="text-base text-muted-foreground">Todavía no lo vio nadie</span>
                    )}
                  </ItemContent>
                </Item>
              ))}
            </ItemGroup>
          </section>
        )}
      </main>
    </AppShell>
  );
}
