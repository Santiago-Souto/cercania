// SIMULATED auth: a demo persona picked in the UI, sent as X-Person-Id.
// The backend honors it only with ALLOW_DEV_IDENTITY_HEADER=1. Replaced by real sessions in CIA-26/32.
// Stored in a cookie (not localStorage) so server components can send it too.
// Ids come from backend/app/seed.py.

export const PERSONAS = [
  { id: "cg_001", name: "Ana", role: "Cuidadora" },
  { id: "fam_001", name: "Carmen", role: "Familia" },
] as const;

export const PERSONA_COOKIE = "cercania_person";
export const DEFAULT_PERSONA_ID: string = PERSONAS[0].id;
