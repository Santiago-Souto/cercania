"use client";
// My patients list with client-side search by name or room. Ticket: CIA-33.
import Link from "next/link";
import type { Route } from "next";
import { useState } from "react";
import { SearchIcon, UsersIcon } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Item, ItemContent, ItemFooter, ItemGroup, ItemMedia, ItemTitle, ItemActions } from "@/components/ui/item";
import { dayTime } from "@/lib/format";
import type { MyPatient } from "@/lib/types";

/** Lowercase without accents, so "jose" finds "José" and "hab 12" finds "Hab. 12". */
const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[.]/g, "").toLowerCase();

type EmptyCopy = { title: string; description: string };
const DEFAULT_EMPTY: EmptyCopy = {
  title: "Todavía no tenés pacientes",
  description: "Pedile a quien cuida al paciente que te invite con este número.",
};

export function PatientList({
  patients,
  hideEmpty = false,
  empty = DEFAULT_EMPTY,
}: {
  patients: MyPatient[];
  hideEmpty?: boolean;
  empty?: EmptyCopy;
}) {
  const [q, setQ] = useState("");
  // Every word must match, so "hab 12" finds "Habitación 12".
  const words = fold(q).split(/\s+/).filter(Boolean);
  const sorted = patients.filter((p) => {
    const text = fold(`${p.display_name} ${p.location ?? ""}`);
    return words.every((w) => text.includes(w));
  });

  return (
    <>
        <InputGroup className="h-12 bg-card">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            aria-label="Buscar paciente"
            placeholder="Buscar paciente"
            className="text-base"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </InputGroup>

        {patients.length === 0 && !hideEmpty && (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <UsersIcon />
              </EmptyMedia>
              <EmptyTitle>{empty.title}</EmptyTitle>
              <EmptyDescription>{empty.description}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}

        {patients.length > 0 && sorted.length === 0 && (
          <p className="px-1 text-sm text-muted-foreground">Ningún paciente coincide con “{q.trim()}”.</p>
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

    </>
  );
}
