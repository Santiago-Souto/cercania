// Add patient + team roles (artboard "AddPatient"). Ticket: CIA-34.
// Skeleton: POST /patients and invites land in CIA-34. Doses are stored as written; nothing is computed (AGENTS.md §7).
import Link from "next/link";
import { PlusIcon, XIcon } from "lucide-react";
import { AppShell, TopBar } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getMembers } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/format";
import type { Role } from "@/lib/types";

const ROLE_BADGE: Record<Role, "success" | "health" | "family" | "warning"> = {
  caregiver: "success",
  doctor: "health",
  nurse: "health",
  institution: "health",
  family: "family",
  patient: "warning",
};

export default async function AddPatientPage() {
  // Preview of how the team looks once saved; real data comes from GET /patients/{id}/members.
  const { members } = await getMembers("pat_001");

  return (
    <AppShell>
      <TopBar back="/patients" title="Nuevo paciente" />
      <form className="flex flex-1 flex-col gap-4 px-4 pb-4">
        <Card className="text-base">
          <CardHeader>
            <CardTitle className="text-lg font-semibold">Datos</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="pname">Nombre</FieldLabel>
                <Input id="pname" placeholder="Nombre y apellido" className="h-12 text-base" />
              </Field>
              <Field>
                <FieldLabel htmlFor="room">Habitación o domicilio</FieldLabel>
                <Input id="room" placeholder="Hab. 12" className="h-12 text-base" />
              </Field>
            </FieldGroup>
          </CardContent>
        </Card>

        <Card className="text-base">
          <CardHeader>
            <CardTitle className="text-lg font-semibold">Plan de cuidado</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Item variant="muted" className="rounded-xl">
              <ItemContent>
                <ItemTitle className="text-sm font-bold">Medicación de ejemplo</ItemTitle>
                <ItemDescription>Según indicación · 08:00 y 20:00</ItemDescription>
              </ItemContent>
              <ItemActions>
                <Button variant="ghost" size="icon-touch" aria-label="Quitar medicación">
                  <XIcon />
                </Button>
              </ItemActions>
            </Item>
            <Button variant="outline" size="touch" className="w-full border-dashed font-bold text-primary">
              <PlusIcon />
              Medicación, indicación o alergia
            </Button>
            <FieldDescription>Se carga tal como lo indicó el médico. CercanIA no calcula ni sugiere dosis.</FieldDescription>
          </CardContent>
        </Card>

        <Card className="text-base">
          <CardHeader>
            <CardTitle className="text-lg font-semibold">Equipo y accesos</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <ItemGroup className="gap-0">
              {members.map((m, i) => (
                <div key={m.user_id}>
                  {i > 0 && <ItemSeparator className="my-0" />}
                  <Item className="px-0">
                    <ItemContent>
                      <ItemTitle className="text-base font-normal">{m.name}</ItemTitle>
                    </ItemContent>
                    <ItemActions>
                      <Badge variant={ROLE_BADGE[m.role]}>{ROLE_LABEL[m.role]}</Badge>
                    </ItemActions>
                  </Item>
                </div>
              ))}
            </ItemGroup>

            <Card size="sm" className="bg-background ring-0">
              <CardHeader>
                <CardTitle className="text-sm font-bold">Invitar a alguien</CardTitle>
              </CardHeader>
              <CardContent>
                <FieldGroup className="gap-3">
                  <Field>
                    <FieldLabel htmlFor="invite">WhatsApp</FieldLabel>
                    <Input id="invite" type="tel" placeholder="+598 9X XXX XXX" className="h-12 bg-card text-base" />
                    <FieldDescription>Le llega la invitación por WhatsApp. No se invita por email.</FieldDescription>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="role">Rol</FieldLabel>
                    <Select defaultValue="family">
                      <SelectTrigger id="role" className="h-12! w-full bg-card text-base">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
                          <SelectItem key={r} value={r}>
                            {ROLE_LABEL[r]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Button type="button" variant="outline-primary" size="touch" className="w-full">
                    Enviar invitación
                  </Button>
                </FieldGroup>
              </CardContent>
            </Card>
            <FieldDescription>
              Familia: solo lectura. Paciente: solo cuenta cómo se siente o pide ayuda. Equipo de salud: ve reportes y alertas.
            </FieldDescription>
          </CardContent>
        </Card>

        <Button asChild size="xl">
          <Link href="/patients/pat_001">Guardar paciente</Link>
        </Button>
      </form>
    </AppShell>
  );
}
