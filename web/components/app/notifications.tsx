"use client";
// Emergency notifications while the tab is open: poll GET /me/notifications every 5 s, show a toast and a
// browser Notification, keep an unread badge. No Web Push / service worker (out of scope, AGENTS.md section 10).
// Same tick polls GET /me/invites, so an invite to the caller's phone shows up without reloading.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { toast } from "sonner";
import { ClientApiError, fetchMyInvites, fetchNotifications, markNotificationRead } from "@/lib/client-api";
import type { AppNotification, MyInvite } from "@/lib/types";

const POLL_MS = 5000;

// Tiny shared store so the layout-level watcher and the shell badge agree on the unread count.
let unread = 0;
const listeners = new Set<() => void>();
function setUnread(n: number) {
  unread = Math.max(0, n);
  listeners.forEach((l) => l());
}
export function useUnreadCount(): number {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => unread,
    () => 0,
  );
}

function load<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage blocked: worst case a toast repeats after reload
  }
}

// Per tab (sessionStorage), cleared on "Salir" so the next person in this tab starts fresh.
const SEEN_KEY = "cercania:seen";
const SINCE_KEY = "cercania:since";
const SEEN_INVITES_KEY = "cercania:seen-invites";

export function clearNotificationState() {
  try {
    sessionStorage.removeItem(SEEN_KEY);
    sessionStorage.removeItem(SINCE_KEY);
    sessionStorage.removeItem(SEEN_INVITES_KEY);
  } catch {
    // storage blocked: nothing stored
  }
}

export function NotificationWatcher() {

  const router = useRouter();
  const routerRef = useRef(router);
  useEffect(() => {
    routerRef.current = router;
  });

  useEffect(() => {
    // Logged-out screens have no session to poll with. Login and "Salir" are full page loads, so the
    // path at mount is enough (and usePathname here would block prerendering of every route).
    if (window.location.pathname.startsWith("/login")) return;
    const seenKey = SEEN_KEY;
    const sinceKey = SINCE_KEY;
    const seen = new Set<string>(load<string[]>(seenKey, []));
    let since = load<string | null>(sinceKey, null);
    const seenInvites = new Set<string>(load<string[]>(SEEN_INVITES_KEY, []));
    // Invites already pending when the tab opens are on screen as cards; only later ones get a toast.
    let invitesPrimed = false;
    let stopped = false;

    // The invite card lives on "Mis pacientes" and on the patient's own view: refresh so it renders there.
    function announceInvite(inv: MyInvite) {
      routerRef.current.refresh();
      toast.info("Te invitaron", {
        description: `${inv.invited_by ?? "Alguien del equipo"} te invitó${inv.patient_display_name ? ` a ${inv.patient_display_name}` : ""}. Aceptala para sumarte.`,
        duration: Infinity,
        action: { label: "Ver", onClick: () => routerRef.current.push("/patients" as Route) },
      });
    }

    async function checkInvites() {
      const { invites } = await fetchMyInvites();
      if (stopped) return;
      const fresh = invites.filter((i) => !seenInvites.has(i.id));
      fresh.forEach((i) => seenInvites.add(i.id));
      save(SEEN_INVITES_KEY, [...seenInvites].slice(-50));
      if (fresh.length && invitesPrimed) announceInvite(fresh[0]);
      invitesPrimed = true;
    }

    function open(n: AppNotification) {
      setUnread(unread - 1);
      markNotificationRead(n.id).catch(() => {});
      routerRef.current.push(`/patients/${n.patient_id}/alerts` as Route);
    }

    function announce(n: AppNotification) {
      toast.warning(n.title, {
        description: n.body,
        duration: Infinity,
        action: { label: "Ver", onClick: () => open(n) },
      });
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          const b = new Notification(n.title, { body: n.body, tag: n.id });
          b.onclick = () => {
            window.focus();
            b.close();
            open(n);
          };
        } catch {
          // some browsers only allow Notification via service worker; the toast still shows
        }
      }
    }

    async function tick() {
      try {
        const res = await fetchNotifications(since ? { since } : { unreadOnly: true });
        if (stopped) return;
        setUnread(res.unread_count);
        // newest first; announce oldest first
        for (const n of [...res.notifications].reverse()) {
          if (n.read_at || seen.has(n.id)) continue;
          seen.add(n.id);
          announce(n);
        }
        save(seenKey, [...seen].slice(-100));
        const newest = res.notifications[0]?.created_at;
        // Only server timestamps: a skewed browser clock must never move the cursor past real notifications.
        if (newest && (!since || newest > since)) since = newest;
        if (since) save(sinceKey, since);
        await checkInvites();
      } catch (err) {
        // Session gone: client-api already sends the browser to /login, stop polling.
        if (err instanceof ClientApiError && err.code === "unauthenticated") {
          stopped = true;
          clearInterval(timer);
        }
        // offline or backend down: try again on the next tick
      }
    }

    const timer = setInterval(tick, POLL_MS);
    tick();
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, []);

  return null;
}
