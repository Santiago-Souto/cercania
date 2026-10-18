"use client";
// Caregivers remove a patient: archived, not erased. Reports stay stored as the evidence trail, but
// nobody keeps access and pending invites are dropped (DELETE /patients/{id}).
import { useState } from "react";
import { toast } from "sonner";
import { ArchiveIcon } from "lucide-react";
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
import { Spinner } from "@/components/ui/spinner";
import { archivePatientAction } from "../../actions";

export function ArchivePatient({ patientId, name }: { patientId: string; name: string }) {
  const [busy, setBusy] = useState(false);

  const archive = async () => {
    setBusy(true);
    try {
      const res = await archivePatientAction(patientId); // redirects to "Mis pacientes" when it worked
      if (res?.error) toast.error(res.error.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" size="touch" disabled={busy}>
          {busy ? <Spinner /> : <ArchiveIcon />}
          Eliminar paciente
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>¿Eliminar a {name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Deja de aparecer para todo el equipo, la familia y el paciente, y se cancelan las invitaciones pendientes. Los reportes quedan guardados como registro, pero nadie podrá verlos desde la app.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancelar</AlertDialogCancel>
          <AlertDialogAction variant="danger" onClick={() => void archive()}>
            Sí, eliminar
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
