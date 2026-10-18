"use client";
// Top bar: unread badge + browser-notification opt-in, and who you are.
// Logged in (CIA-32): a "Salir" button (POST /auth/logout). Otherwise the SIMULATED persona picker (sent as X-Person-Id).
import { useEffect, useState } from "react";
import { BellIcon, BellRingIcon, LogOutIcon } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { isLoggedIn } from "@/lib/api-shared";
import { authErrorMessage, logout } from "@/lib/auth";
import { currentPersonId, switchPerson } from "@/lib/client-api";
import { PERSONAS } from "@/lib/persona";
import { useUnreadCount } from "./notifications";

export function DemoBar() {
  const unread = useUnreadCount();
  const [person, setPerson] = useState<string | null>(null);
  const [loggedIn, setLoggedIn] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("unsupported");

  useEffect(() => {
    // Client-only values: set after mount to keep server and client HTML identical.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPerson(currentPersonId());
    setLoggedIn(isLoggedIn());
    setPerm(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  async function enableAlerts() {
    // Must run from a click: browsers ignore permission prompts without a user gesture.
    setPerm(await Notification.requestPermission());
  }

  async function signOut() {
    setLeaving(true);
    try {
      await logout();
    } catch (err) {
      // The session may still be valid: stay logged in and let the user retry.
      toast.error("No pudimos cerrar la sesión", {
        description: authErrorMessage(err),
        action: { label: "Reintentar", onClick: () => void signOut() },
      });
      setLeaving(false);
      return;
    }
    // Full load: drop server-rendered data and stop the notification poller.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login?mode=login&notice=logged_out";
  }

  if (loggedIn) {
    return (
      <div className="flex items-center gap-2 border-b px-3 py-2 text-[13px]">
        <Button size="sm" variant="outline" onClick={signOut} disabled={leaving}>
          {leaving ? <Spinner /> : <LogOutIcon />}
          Salir
        </Button>
        <span className="ml-auto flex items-center gap-2">
          {perm === "default" && (
            <Button size="sm" variant="outline" onClick={enableAlerts}>
              <BellRingIcon />
              Activar avisos
            </Button>
          )}
          <UnreadBell unread={unread} />
        </span>
      </div>
    );
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
        <UnreadBell unread={unread} />
      </span>
    </div>
  );
}

function UnreadBell({ unread }: { unread: number }) {
  return (
    <span className="relative inline-flex" aria-label={`${unread} avisos sin leer`}>
      <BellIcon className="size-5" />
      {unread > 0 && (
        <Badge variant="danger" className="absolute -top-2 -right-3 h-4 min-w-4 px-1 text-[10px]">
          {unread}
        </Badge>
      )}
    </span>
  );
}
