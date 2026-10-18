// Team members with role badges, plus pending invites marked "pendiente" (CIA-34). No hooks: usable
// from server and client components.
import { XIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemSeparator, ItemTitle } from "@/components/ui/item";
import { ROLE_LABEL } from "@/lib/format";
import type { Role } from "@/lib/types";

export const ROLE_BADGE: Record<Role, "success" | "health" | "family" | "warning"> = {
  caregiver: "success",
  doctor: "health",
  nurse: "health",
  institution: "health",
  family: "family",
  patient: "warning",
};

type Row = { key: string; name: string; role: Role; pending?: string; onRemove?: () => void };

export function TeamList({ rows }: { rows: Row[] }) {
  return (
    <ItemGroup className="gap-0">
      {rows.map((r, i) => (
        <div key={r.key}>
          {i > 0 && <ItemSeparator className="my-0" />}
          <Item className="px-0">
            <ItemContent>
              <ItemTitle className="text-base font-normal">{r.name}</ItemTitle>
              {r.pending && <ItemDescription>{r.pending}</ItemDescription>}
            </ItemContent>
            <ItemActions>
              {r.pending && <Badge variant="neutral">pendiente</Badge>}
              <Badge variant={ROLE_BADGE[r.role]}>{ROLE_LABEL[r.role]}</Badge>
              {r.onRemove && (
                <Button type="button" variant="ghost" size="icon-touch" aria-label={`Quitar invitación a ${r.name}`} onClick={r.onRemove}>
                  <XIcon />
                </Button>
              )}
            </ItemActions>
          </Item>
        </div>
      ))}
    </ItemGroup>
  );
}
