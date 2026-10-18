"use client";
import { toast } from "sonner";
import { InviteForm } from "@/components/app/invite-form";
import { invitePatientAction } from "../actions";

export function InvitePatient() {
  return (
    <InviteForm
      title="Celular del paciente"
      submitLabel="Enviar invitación"
      roles={["patient"]}
      onInvite={async (phone) => {
        try {
          const res = await invitePatientAction(phone);
          if ("error" in res) return res.error.message;
          toast.success("Invitación guardada. Cuando entre con ese número y la acepte, aparece en tu lista.");
          return null;
        } catch {
          return "No pudimos enviar la invitación. Revisá tu conexión y probá de nuevo.";
        }
      }}
    />
  );
}
