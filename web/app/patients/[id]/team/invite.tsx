"use client";
// Sends an invite right away from the team page (CIA-34); the page re-renders with it as "pendiente".
import { toast } from "sonner";
import { InviteForm } from "@/components/app/invite-form";
import { inviteAction } from "../../actions";

export function TeamInvite({ patientId }: { patientId: string }) {
  return (
    <InviteForm
      submitLabel="Enviar invitación"
      onInvite={async (phone, role) => {
        try {
          const res = await inviteAction(patientId, phone, role);
          if ("error" in res) return res.error.message;
          toast.success("Invitación guardada. Va a tener acceso cuando entre con ese número.");
          return null;
        } catch {
          return "No pudimos enviar la invitación. Revisá tu conexión y probá de nuevo.";
        }
      }}
    />
  );
}
