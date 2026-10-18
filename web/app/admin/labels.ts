// Shared by the admin page (server) and its forms (client). Not a "use client" module, so the server
// page gets the real object: values imported from a client module are only references there.
import { ROLE_LABEL } from "@/lib/format";
import type { AdminRole } from "@/lib/types";

export const ADMIN_ROLE_LABEL: Record<AdminRole, string> = { ...ROLE_LABEL, admin: "Administración" };
