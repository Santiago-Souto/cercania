// Where a logged-in person lands. Shared by the code screen (browser) and the login / home pages (server).

import type { Route } from "next";
import type { Membership } from "./types";

/**
 * Only same-site paths (no open redirect through ?next=). Browsers read "/\host" and "/<tab>/host" as
 * "//host", so a backslash or control character anywhere rejects the path.
 */
export function safeNext(next: string | null | undefined): string | undefined {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/login")) return undefined;
  return /[\\\u0000-\u001f\u007f]/.test(next) ? undefined : next;
}

/** Where to go after login: a lone patient-role membership opens the patient view, everyone else My patients. */
export function landingFor(memberships: Membership[], next?: string): Route {
  if (memberships.length === 1 && memberships[0].role === "patient") {
    return `/patients/${memberships[0].patient_id}/me` as Route;
  }
  return (next ?? "/patients") as Route;
}
