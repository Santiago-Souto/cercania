// Patient team: members, pending invites and invite form (artboard "AddPatient", team card). Ticket: CIA-34.
import { AppShell, TopBar } from "@/components/app/shell";
import { TeamList } from "@/components/app/team-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldDescription } from "@/components/ui/field";
import { getMembers, getMyPatients, getPatient } from "@/lib/api";
import { TeamInvite } from "./invite";

export default async function TeamPage(props: PageProps<"/patients/[id]/team">) {
  const { id } = await props.params;
  const [patient, { members, invites }, mine] = await Promise.all([getPatient(id), getMembers(id), getMyPatients()]);
  // Only caregivers invite (AGENTS.md section 6); the backend enforces it too.
  const canInvite = mine.find((p) => p.id === id)?.role === "caregiver";

  return (
    <AppShell>
      <TopBar back={`/patients/${id}`} title="Equipo y accesos" subtitle={patient.display_name} />
      <main className="flex flex-1 flex-col gap-4 px-4 pb-4">
        <Card className="text-base">
          <CardHeader>
            <CardTitle className="text-lg font-semibold">Equipo</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <TeamList
              rows={[
                ...members.map((m) => ({ key: m.user_id, name: m.name, role: m.role })),
                ...invites.map((inv) => ({ key: inv.id, name: inv.contact, role: inv.role, pending: "Invitación pendiente: la ve al entrar con ese número" })),
              ]}
            />
            {canInvite && <TeamInvite patientId={id} />}
            <FieldDescription>
              Familia: solo lectura. Paciente: solo cuenta cómo se siente o pide ayuda. Equipo de salud: ve reportes y alertas. La persona invitada ve la invitación al entrar con ese número y recibe el rol cuando la acepta.
            </FieldDescription>
          </CardContent>
        </Card>
      </main>
    </AppShell>
  );
}
