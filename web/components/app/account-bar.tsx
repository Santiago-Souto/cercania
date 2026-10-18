"use client";
// Logged-in strip on every app screen: unread badge, browser-notification opt-in and "Salir".
import { useEffect, useState } from "react";
import { BellIcon, BellRingIcon, LogOutIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth";
import { clearNotificationState, useUnreadCount } from "./notifications";

export function AccountBar() {
  const unread = useUnreadCount();
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("unsupported");
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    // Client-only value: set after mount to keep server and client HTML identical.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPerm(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  async function enableAlerts() {
    // Must run from a click: browsers ignore permission prompts without a user gesture.
    setPerm(await Notification.requestPermission());
  }

  async function signOut() {
    setLeaving(true);
    await logout();
    clearNotificationState();
    // Full load: drops every client cache and stops the notification poller of the old session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login?mode=login");
  }

  return (
    <div className="flex items-center gap-2 border-b px-3 py-1.5 text-[13px]">
      {perm === "default" && (
        <Button size="sm" variant="outline" onClick={enableAlerts}>
          <BellRingIcon />
          Activar avisos
        </Button>
      )}
      <span className="ml-auto flex items-center gap-3">
        <span className="relative inline-flex" aria-label={`${unread} avisos sin leer`}>
          <BellIcon className="size-5" />
          {unread > 0 && (
            <Badge variant="danger" className="absolute -top-2 -right-3 h-4 min-w-4 px-1 text-[10px]">
              {unread}
            </Badge>
          )}
        </span>
        <Button size="sm" variant="ghost" onClick={signOut} disabled={leaving}>
          <LogOutIcon />
          Salir
        </Button>
      </span>
    </div>
  );
}
