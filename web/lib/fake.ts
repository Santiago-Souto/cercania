// SIMULATED: fake data shaped exactly like docs/contract.md, used while NEXT_PUBLIC_USE_FAKE_DATA=1.
// Declared in README "Simulated". All names and health data are fictional.
// Nothing here is presented as AI output in production: CIA-14 switches every screen to the real API.

import type {
  Member,
  Invite,
  Message,
  MyPatient,
  Patient,
  PatientMessage,
  ProcessResult,
  QueryResponse,
  Report,
} from "./types";

export const fakePatient: Patient = {
  id: "pat_001",
  display_name: "Rosa (ficticia)",
  location: "Hab. 12",
  care_plan: {
    medications: [{ id: "med_002", name: "Medicación de ejemplo", dose: "según indicación", times: ["08:00", "20:00"] }],
    indications: ["Hidratación", "Asistir al caminar"],
    allergies: [],
  },
};

export const fakeReports: Report[] = [
  {
    id: "rep_123",
    version: 1,
    created_at: "2026-10-17T21:05:00-03:00",
    caregiver: { id: "usr_001", display_name: "Ana (ficticia)" },
    transcript:
      "Rosa casi no comió nada en la cena. La pastilla de las ocho se la tomó con agua. Fue hasta el comedor con el andador. No se quejó de nada. Todo tranquilo, sin novedades.",
    audio_url: "/reports/rep_123/audio",
    audio_duration_sec: 48,
    items: [
      { item: "appetite", value: "Comió poco en la cena", level: "low", quote: "casi no comió nada en la cena", quote_verified: true },
      { item: "medication", value: "Tomó la dosis de las 20:00", quote: "la pastilla de las ocho se la tomó con agua", quote_verified: true },
      { item: "mobility", value: "Caminó con andador", quote: "fue hasta el comedor con el andador", quote_verified: true },
      { item: "mood", value: "Tranquila", quote: "estuvo tranquila toda la tarde", quote_verified: false },
      { item: "pain", value: "Sin dolor", quote: "no se quejó de nada", quote_verified: true },
      { item: "incidents", value: "Ninguno", quote: "todo tranquilo, sin novedades", quote_verified: true },
      { item: "sleep", value: null, quote: null, quote_verified: null },
      { item: "urination", value: null, quote: null, quote_verified: null },
    ],
    missing_items: ["sleep", "urination"],
    alerts: [
      {
        type: "omission",
        detail: "El plan indica una dosis a las 08:00. El reporte no la menciona.",
        plan_ref: "med_002",
        evidence_quote: null,
      },
      {
        type: "change",
        detail: "Apetito bajo 3 turnos seguidos.",
        report_refs: ["rep_120", "rep_121", "rep_123"],
      },
    ],
    red_flag: false,
  },
  {
    id: "rep_122",
    version: 1,
    created_at: "2026-10-17T14:10:00-03:00",
    caregiver: { id: "usr_002", display_name: "Luis (ficticio)" },
    transcript: "A la mañana se resbaló en el baño, la ayudamos a levantarse y quedó acostada.",
    audio_url: "/reports/rep_122/audio",
    audio_duration_sec: 72,
    items: [
      { item: "incidents", value: "Se resbaló en el baño", quote: "se resbaló en el baño", quote_verified: true },
      { item: "appetite", value: null, quote: null, quote_verified: null },
      { item: "sleep", value: null, quote: null, quote_verified: null },
      { item: "urination", value: null, quote: null, quote_verified: null },
      { item: "medication", value: null, quote: null, quote_verified: null },
      { item: "mood", value: null, quote: null, quote_verified: null },
      { item: "mobility", value: null, quote: null, quote_verified: null },
      { item: "pain", value: null, quote: null, quote_verified: null },
    ],
    missing_items: ["appetite", "sleep", "urination", "medication", "mood", "mobility", "pain"],
    alerts: [],
    red_flag: true,
    red_flag_quote: "se resbaló en el baño",
  },
  {
    id: "rep_121",
    version: 1,
    created_at: "2026-10-16T21:02:00-03:00",
    caregiver: { id: "usr_001", display_name: "Ana (ficticia)" },
    transcript: "Cenó poco, dejó la mitad del plato. Durmió bien.",
    audio_url: "/reports/rep_121/audio",
    audio_duration_sec: 55,
    items: [
      { item: "appetite", value: "Comió poco", quote: "dejó la mitad del plato", quote_verified: true },
      { item: "sleep", value: "Durmió bien", quote: "durmió bien", quote_verified: true },
      { item: "urination", value: null, quote: null, quote_verified: null },
      { item: "medication", value: null, quote: null, quote_verified: null },
      { item: "mood", value: null, quote: null, quote_verified: null },
      { item: "mobility", value: null, quote: null, quote_verified: null },
      { item: "pain", value: null, quote: null, quote_verified: null },
      { item: "incidents", value: null, quote: null, quote_verified: null },
    ],
    missing_items: ["urination", "medication", "mood", "mobility", "pain", "incidents"],
    alerts: [{ type: "missing_item", detail: "No habló de medicación." }],
    red_flag: false,
  },
];

// The example ProcessResult from docs/contract.md, returned whatever was sent: it does not read the input.
// The "Datos de prueba ficticios" banner is on whenever this is used.
export const fakeProcessResult: ProcessResult = {
  status: "ok",
  report: { id: "rep_123", version: 1 },
  items: [
    { item: "appetite", value: "comió poco en la cena", level: "low", quote: "casi no comio nada en la cena", quote_verified: true },
  ],
  missing_items: ["sleep", "urination"],
  alerts: [{ type: "omission", detail: "08:00: no se mencionó.", plan_ref: "med_002", report_refs: ["rep_123"] }],
  red_flag: false,
  triage: { status: "ok", emergency: false, reason: null, quote: null, quote_verified: null },
  confirmation_text: "Registré: apetito: casi no comió en la cena. No mencionaste: sueño, diuresis. Podés mandar otra nota.",
};

export const fakeQuery: QueryResponse = {
  answer: "En los últimos 3 turnos se reportó que comió poco.",
  citations: [
    { report_id: "rep_123", quote: "casi no comió nada en la cena", audio_start_sec: 12, audio_end_sec: 15 },
    { report_id: "rep_121", quote: "dejó la mitad del plato", audio_start_sec: 20, audio_end_sec: 23 },
  ],
  confidence: "answered",
  note: null,
};

export const fakeMyPatients: MyPatient[] = [
  {
    id: "pat_001",
    display_name: "Rosa (ficticia)",
    location: "Hab. 12",
    role: "caregiver",
    last_report_at: "2026-10-17T21:05:00-03:00",
    open_alerts: 2,
    red_flag: true,
    missing_report: false,
  },
  {
    id: "pat_003",
    display_name: "Elena (ficticia)",
    location: "Hab. 3",
    role: "caregiver",
    last_report_at: "2026-10-17T08:30:00-03:00",
    open_alerts: 0,
    red_flag: false,
    missing_report: true,
  },
  {
    id: "pat_002",
    display_name: "Jorge (ficticio)",
    location: "Hab. 7",
    role: "caregiver",
    last_report_at: "2026-10-17T20:40:00-03:00",
    open_alerts: 0,
    red_flag: false,
    missing_report: false,
  },
];

export const fakeMembers: Member[] = [
  { user_id: "usr_001", name: "Ana (vos)", role: "caregiver" },
  { user_id: "usr_004", name: "Dra. López (ficticia)", role: "doctor" },
  { user_id: "usr_005", name: "Marta (ficticia)", role: "family" },
  { user_id: "usr_006", name: "Rosa (ficticia)", role: "patient" },
];

export const fakeInvites: Invite[] = [];

export const fakePatientMessages: PatientMessage[] = [
  {
    id: "pm_001",
    kind: "feeling",
    text: "me duele un poco la rodilla",
    created_at: "2026-10-17T10:20:00-03:00",
    seen_by: [{ user_id: "usr_001", name: "Ana" }],
  },
];

export const fakeMessages: Message[] = [
  {
    id: "msg_001",
    from: { user_id: "usr_005", name: "Marta (ficticia)", role: "family" },
    text: "Hola doctora, vi que mamá viene comiendo poco. ¿Hay que preocuparse?",
    created_at: "2026-10-17T15:02:00-03:00",
    read: true,
    mine: true,
  },
  {
    id: "msg_002",
    from: { user_id: "usr_004", name: "Dra. López (ficticia)", role: "doctor" },
    text: "Hola Marta, lo vi en los reportes. Mañana paso a verla en la ronda de la mañana.",
    created_at: "2026-10-17T16:40:00-03:00",
    read: true,
    mine: false,
  },
];
