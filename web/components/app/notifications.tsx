"use client";
// Emergency notifications while the tab is open: poll GET /me/notifications every 5 s, show a toast and a
// browser Notification, keep an unread badge. No Web Push / service worker (out of scope, AGENTS.md section 10).
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { toast } from "sonner";
import { fetchNotifications, markNotificationRead, currentPersonId } from "@/lib/client-api";
import { USE_FAKE } from "@/lib/api-shared";
import type { AppNotification } from "@/lib/types";

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

export function NotificationWatcher() {
  const router = useRouter();
  const routerRef = useRef(router);
  useEffect(() => {
    routerRef.current = router;
  });

  useEffect(() => {
    if (USE_FAKE) return;
    const person = currentPersonId();
    const seenKey = `cercania:seen:${person}`;
    const sinceKey = `cercania:since:${person}`;
    const seen = new Set<string>(load<string[]>(seenKey, []));
    let since = load<string | null>(sinceKey, null);
    let stopped = false;

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
      } catch {
        // offline or backend down: try again on the next tick
      }
    }

    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, []);

  return null;
}
