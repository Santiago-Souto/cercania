// My patients (artboard "Patients"). Ticket: CIA-33.
import Link from "next/link";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { PlusIcon, SearchIcon, UsersIcon } from "lucide-react";
import { AppShell, BottomBar, Brand } from "@/components/app/shell";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Item, ItemContent, ItemFooter, ItemGroup, ItemMedia, ItemTitle, ItemActions } from "@/components/ui/item";
import { getMyPatients } from "@/lib/api";
import { dayTime } from "@/lib/format";

export default async function PatientsPage() {
  const patients = await getMyPatients();
  // A patient's only screen is their own view (CIA-35): no list, no other navigation.
  if (patients.length === 1 && patients[0].role === "patient") redirect(`/patients/${patients[0].id}/me` as Route);
  // Red flags first, then by open alerts, then missing reports.
  const sorted = [...patients].sort(
    (a, b) =>
      Number(b.red_flag ?? false) - Number(a.red_flag ?? false) ||
      (b.open_alerts ?? 0) - (a.open_alerts ?? 0) ||
      Number(b.missing_report ?? false) - Number(a.missing_report ?? false),
  );

  return (
    <AppShell>
      <header className="px-5 pt-5 pb-3">
        <Brand />
      </header>
      <main className="flex flex-1 flex-col gap-3 px-4 pb-4">
        <h1 className="text-[28px] font-bold">Mis pacientes</h1>

        {/* Search becomes client-side filtering in CIA-33. */}
        <InputGroup className="h-12 bg-card">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput type="search" aria-label="Buscar paciente" placeholder="Buscar por nombre o habitación" className="text-base" />
        </InputGroup>

        {sorted.length === 0 && (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <UsersIcon />
              </EmptyMedia>
              <EmptyTitle>Todavía no tenés pacientes</EmptyTitle>
              <EmptyDescription>Agregá uno o pedile a la residencia que te invite.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}

        <ItemGroup className="gap-2.5">
          {sorted.map((p) => (
            <Item key={p.id} asChild variant="outline" className="rounded-xl bg-card px-4 py-3.5">
              <Link href={(p.role === "patient" ? `/patients/${p.id}/me` : `/patients/${p.id}`) as Route}>
                <ItemMedia>
                  <Avatar className="size-11">
                    <AvatarFallback className="bg-secondary font-heading text-lg font-bold text-primary">
                      {p.display_name[0]}
                    </AvatarFallback>
                  </Avatar>
                </ItemMedia>
                <ItemContent>
                  <ItemTitle className="text-base font-bold">{p.display_name}</ItemTitle>
                </ItemContent>
                <ItemActions className="text-[13px] text-muted-foreground">{p.location}</ItemActions>
                <ItemFooter className="justify-start gap-1.5 pl-14">
                  {p.red_flag && <Badge variant="danger">Señal de alarma</Badge>}
                  {(p.open_alerts ?? 0) > 0 && (
                    <Badge variant="warning">
                      {p.open_alerts} {p.open_alerts === 1 ? "alerta" : "alertas"}
                    </Badge>
                  )}
                  {p.missing_report && <Badge variant="missing">Falta el reporte del turno</Badge>}
                  {p.role !== "patient" && !p.red_flag && !p.open_alerts && !p.missing_report && (
                    <Badge variant="success">Al día{p.last_report_at ? ` · ${dayTime(p.last_report_at).toLowerCase()}` : ""}</Badge>
                  )}
                </ItemFooter>
              </Link>
            </Item>
          ))}
        </ItemGroup>

        <p className="px-1 text-[13px] text-muted-foreground">Enfermería y médicos ven esta misma lista con sus pacientes asignados.</p>
      </main>
      <BottomBar>
        <Button asChild size="xl">
          <Link href="/patients/new">
            <PlusIcon />
            Agregar paciente
          </Link>
        </Button>
      </BottomBar>
    </AppShell>
  );
}
