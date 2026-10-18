"use client";
// SIMULATED identity for the demo: pick who you are (sent as X-Person-Id) + unread badge + browser-notification opt-in.
// Replaced by the real 6-digit code login (CIA-26/32).
import { useEffect, useState } from "react";
import { BellIcon, BellRingIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { currentPersonId, switchPerson } from "@/lib/client-api";
import { PERSONAS } from "@/lib/persona";
import { useUnreadCount } from "./notifications";

export function DemoBar() {
  const unread = useUnreadCount();
  const [person, setPerson] = useState<string | null>(null);
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("unsupported");

  useEffect(() => {
    // Client-only values: set after mount to keep server and client HTML identical.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPerson(currentPersonId());
    setPerm(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  async function enableAlerts() {
    // Must run from a click: browsers ignore permission prompts without a user gesture.
    setPerm(await Notification.requestPermission());
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b bg-warning/40 px-3 py-2 text-[13px]">
      <Badge variant="warning">Simulado</Badge>
      <span className="text-muted-foreground">Usuario de prueba:</span>
      {PERSONAS.map((p) => (
        <Button
          key={p.id}
          size="sm"
          variant={person === p.id ? "default" : "outline"}
          aria-pressed={person === p.id}
          onClick={() => switchPerson(p.id)}
        >
          {p.name} · {p.role}
        </Button>
      ))}
      <span className="ml-auto flex items-center gap-2">
        {perm === "default" && (
          <Button size="sm" variant="outline" onClick={enableAlerts}>
            <BellRingIcon />
            Activar avisos
          </Button>
        )}
        <span className="relative inline-flex" aria-label={`${unread} avisos sin leer`}>
          <BellIcon className="size-5" />
          {unread > 0 && (
            <Badge variant="danger" className="absolute -top-2 -right-3 h-4 min-w-4 px-1 text-[10px]">
              {unread}
            </Badge>
          )}
        </span>
      </span>
    </div>
  );
}
