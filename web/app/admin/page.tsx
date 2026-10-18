// Users and roles (CIA-48). Admins only: list people, assign roles, pre-register phones.
// No clinical data here, by design: an admin sees names, phones and roles, nothing else.
import Link from "next/link";
import { ShieldIcon } from "lucide-react";
import { AppShell, Brand } from "@/components/app/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { getAdminPeople, getMe } from "@/lib/api";
import { AssignRole, DeletePreRegistration, MakeAdmin, PreRegisterForm, RemoveRole } from "./admin-forms";
import { ADMIN_ROLE_LABEL, membershipLabel } from "./labels";

export default async function AdminPage() {
  const me = await getMe();
  if (!me.is_admin) {
    return (
      <AppShell>
        <main className="flex flex-1 flex-col gap-3 px-4 py-6">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ShieldIcon />
              </EmptyMedia>
              <EmptyTitle>Solo para personas administradoras</EmptyTitle>
              <EmptyDescription>Tu cuenta no puede asignar roles.</EmptyDescription>
            </EmptyHeader>
          </Empty>
          <Button asChild variant="outline" size="touch">
            <Link href="/patients">Volver a mis pacientes</Link>
          </Button>
        </main>
      </AppShell>
    );
  }
  const { people, pre_registrations: pending, patients } = await getAdminPeople();

  return (
    <AppShell>
      <header className="px-5 pt-5 pb-3">
        <Brand />
      </header>
      <main className="flex flex-1 flex-col gap-4 px-4 pb-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold">Usuarios y roles</h1>
          <p className="text-[13px] text-muted-foreground">
            Asignás roles; no ves reportes, alertas ni mensajes. Las familias entran por invitación de quien cuida, y quien se
            registra por su cuenta entra como paciente.
          </p>
        </div>

        <Card size="sm">
          <CardHeader>
            <CardTitle className="text-base font-bold">Registrar un número con su rol</CardTitle>
          </CardHeader>
          <CardContent>
            <PreRegisterForm patients={patients} />
          </CardContent>
        </Card>

        {pending.length > 0 && (
          <section aria-label="Pendientes de registro" className="flex flex-col gap-2">
            <h2 className="text-lg font-bold">Pendientes de registro</h2>
            <ItemGroup className="gap-0 overflow-hidden rounded-xl border bg-card">
              {pending.map((p) => (
                <Item key={p.id} className="rounded-none border-b px-4 py-3 last:border-b-0">
                  <ItemContent>
                    <ItemTitle className="text-base">{p.phone}</ItemTitle>
                    <ItemDescription className="text-sm">
                      {ADMIN_ROLE_LABEL[p.role]}
                      {p.patient_name ? ` de ${p.patient_name}` : p.role === "caregiver" ? ", sin pacientes" : ""}
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions>
                    <Badge variant="warning">pendiente de registro</Badge>
                    <DeletePreRegistration pre={p} />
                  </ItemActions>
                </Item>
              ))}
            </ItemGroup>
          </section>
        )}

        <section aria-label="Personas registradas" className="flex flex-col gap-2">
          <h2 className="text-lg font-bold">Personas registradas</h2>
          {people.map((person) => (
            <Card key={person.id} size="sm">
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2 text-base font-bold">
                  {person.name}
                  {person.is_admin && <Badge variant="health">Administración</Badge>}
                </CardTitle>
                <p className="text-[13px] text-muted-foreground">{person.phone}</p>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {person.memberships.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    {person.is_caregiver ? "Cuidador/a, sin pacientes asignados." : "Sin roles con pacientes."}
                  </p>
                )}
                {person.memberships.length > 0 && (
                  <ItemGroup className="gap-1">
                    {person.memberships.map((m) => {
                      const label = membershipLabel(m, person.name);
                      return (
                        <Item key={m.patient_id} variant="muted" size="sm" className="rounded-lg">
                          <ItemContent>
                            <ItemTitle className="text-sm font-normal">
                              <span className="font-bold">{label.role}</span> {label.detail}
                            </ItemTitle>
                          </ItemContent>
                          <ItemActions>
                            <RemoveRole person={person} membership={m} />
                          </ItemActions>
                        </Item>
                      );
                    })}
                  </ItemGroup>
                )}
                <AssignRole person={person} patients={patients} />
                {!person.is_admin && <MakeAdmin person={person} />}
              </CardContent>
            </Card>
          ))}
        </section>
      </main>
    </AppShell>
  );
}
