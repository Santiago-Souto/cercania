// Where a logged-in person lands. Shared by the code screen (browser) and the login / home pages (server).

import type { Route } from "next";
import type { Membership } from "./types";

/** Only same-site paths, never "//host" or a full URL (no open redirect through ?next=). */
export function safeNext(next: string | null | undefined): string | undefined {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : undefined;
}

/** Where to go after login: a lone patient-role membership opens the patient view, everyone else My patients. */
export function landingFor(memberships: Membership[], next?: string): Route {
  if (memberships.length === 1 && memberships[0].role === "patient") {
    return `/patients/${memberships[0].patient_id}/me` as Route;
  }
  return (next ?? "/patients") as Route;
}
