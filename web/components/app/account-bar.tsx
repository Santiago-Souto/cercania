"use client";
// Logged-in strip on every app screen: unread badge, browser-notification opt-in and "Salir".
// The opt-in opens as a popup the first time this browser opens the app; after "Ahora no" it stays as a button.
// Its text fits the person's roles, and people who are never notified (a patient, an admin without
// patients) are not asked at all (CIA-59).
import { useEffect, useState } from "react";
import { BellIcon, BellRingIcon, LogOutIcon } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth";
import { ClientApiError, fetchMe } from "@/lib/client-api";
import { GENERIC_NOTIFICATION_TEXT, notificationText } from "./notification-copy";
import { clearNotificationState, useUnreadCount } from "./notifications";

// Per browser (localStorage), not per tab: the popup is asked once, not on every new tab or login.
const ASKED_KEY = "cercania:notif-asked";

function wasAsked(): boolean {
  try {
    return localStorage.getItem(ASKED_KEY) === "1";
  } catch {
    return false;
  }
}
function markAsked() {
  try {
    localStorage.setItem(ASKED_KEY, "1");
  } catch {
    // storage blocked: the popup may show again on the next visit
  }
}

export function AccountBar() {
  const unread = useUnreadCount();
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("unsupported");
  const [askOpen, setAskOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  // undefined while loading; null = this person is never notified (no prompt, no bell).
  const [text, setText] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    // Client-only values: set after mount to keep server and client HTML identical.
    const p = typeof Notification === "undefined" ? "unsupported" : Notification.permission;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPerm(p);
    let cancelled = false;
    fetchMe().then(
      (me) => notificationText(me),
      // Logged out (a login screen or its loading state): nothing to ask. Other errors: ask, neutrally.
      (err: unknown) => (err instanceof ClientApiError && err.code === "unauthenticated" ? null : GENERIC_NOTIFICATION_TEXT),
    ).then((t) => {
      if (cancelled) return;
      setText(t);
      if (t && p === "default" && !wasAsked()) setAskOpen(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const notified = text !== null && text !== undefined;

  async function enableAlerts() {
    // Must run from a click: browsers ignore permission prompts without a user gesture.
    markAsked();
    setAskOpen(false);
    setPerm(await Notification.requestPermission());
  }

  function onAskOpenChange(open: boolean) {
    setAskOpen(open);
    if (!open) markAsked();
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
      {perm === "default" && notified && (
        <Button size="sm" variant="outline" onClick={enableAlerts}>
          <BellRingIcon />
          Activar avisos
        </Button>
      )}
      <span className="ml-auto flex items-center gap-3">
        {text !== null && (
          <span className="relative inline-flex" aria-label={`${unread} avisos sin leer`}>
            <BellIcon className="size-5" />
            {unread > 0 && (
              <Badge variant="danger" className="absolute -top-2 -right-3 h-4 min-w-4 px-1 text-[10px]">
                {unread}
              </Badge>
            )}
          </span>
        )}
        <Button size="sm" variant="ghost" onClick={signOut} disabled={leaving}>
          <LogOutIcon />
          Salir
        </Button>
      </span>

      <AlertDialog open={askOpen} onOpenChange={onAskOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Activamos los avisos?</AlertDialogTitle>
            <AlertDialogDescription>{text ?? GENERIC_NOTIFICATION_TEXT}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Ahora no</AlertDialogCancel>
            <AlertDialogAction onClick={() => void enableAlerts()}>
              <BellRingIcon />
              Activar avisos
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
