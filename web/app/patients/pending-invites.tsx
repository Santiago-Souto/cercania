"use client";
// Invitations addressed to the caller's own phone, on "Mis pacientes". Nothing is joined until the
// person accepts here (POST /me/invites/{id}/accept); declining deletes the invite. CIA-27.
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemFooter, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { ROLE_LABEL } from "@/lib/format";
import type { MyInvite } from "@/lib/types";
import { answerInviteAction } from "./actions";

export function PendingInvites({ invites }: { invites: MyInvite[] }) {
  const [busy, setBusy] = useState<{ id: string; accept: boolean } | null>(null);

  const answer = async (inv: MyInvite, accept: boolean) => {
    setBusy({ id: inv.id, accept });
    try {
      const res = await answerInviteAction(inv.id, accept);
      if ("error" in res) toast.error(res.error.message);
      else if (accept) toast.success(`Ya podés acompañar a ${inv.patient_display_name}`);
      else toast(`Rechazaste la invitación para ${inv.patient_display_name}`);
    } catch {
      toast.error("No pudimos responder la invitación. Probá de nuevo.");
    } finally {
      setBusy(null);
    }
  };

  if (invites.length === 0) return null;
  return (
    <section className="flex flex-col gap-2.5" aria-label="Invitaciones">
      <h2 className="text-lg font-semibold">{invites.length === 1 ? "Te invitaron" : "Tenés invitaciones"}</h2>
      <ItemGroup className="gap-2.5">
        {invites.map((inv) => (
          <Item key={inv.id} variant="outline" className="rounded-xl bg-card px-4 py-3.5">
            <ItemContent>
              <ItemTitle className="text-base font-bold">{inv.patient_display_name}</ItemTitle>
              <ItemDescription>{inv.invited_by ? `Te invitó ${inv.invited_by}` : "Te invitaron"}</ItemDescription>
            </ItemContent>
            <ItemActions>
              <Badge variant="secondary">{ROLE_LABEL[inv.role]}</Badge>
            </ItemActions>
            <ItemFooter className="gap-2">
              <Button size="touch" className="flex-1" disabled={busy !== null} onClick={() => answer(inv, true)}>
                {busy?.id === inv.id && busy.accept && <Spinner />}
                Aceptar
              </Button>
              <Button variant="outline" size="touch" className="flex-1" disabled={busy !== null} onClick={() => answer(inv, false)}>
                {busy?.id === inv.id && !busy.accept && <Spinner />}
                Rechazar
              </Button>
            </ItemFooter>
          </Item>
        ))}
      </ItemGroup>
    </section>
  );
}
