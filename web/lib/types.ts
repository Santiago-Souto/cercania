// Shapes from docs/contract.md. Change them only together with the contract.

export type ChecklistItem =
  | "appetite"
  | "sleep"
  | "urination"
  | "medication"
  | "mood"
  | "mobility"
  | "pain"
  | "incidents";

export type Role = "caregiver" | "family" | "patient" | "doctor" | "nurse" | "institution";

export type Medication = { id?: string; name: string; dose: string; times: string[] };

export type CarePlan = {
  medications: Medication[];
  indications: string[];
  allergies: string[];
};

export type EmergencyContact = { name: string; phone: string };

export type Patient = {
  id: string;
  display_name: string;
  location?: string;
  emergency_contact: EmergencyContact | null;
  care_plan: CarePlan | null;
};

export type MedicationDose = {
  plan_ref: string;
  time: string;
  given: boolean | null;
  quote?: string | null;
  quote_verified?: boolean | null;
};

export type ReportItem = {
  item: ChecklistItem;
  value: string | null;
  /** Coarse category code uses to compare over time (e.g. appetite normal / low / none). Optional for display. */
  level?: string | null;
  /** Extra structure; medication items carry `doses` (docs/contract.md). Null for the rest. */
  details?: { doses?: MedicationDose[] } | null;
  quote: string | null;
  quote_verified: boolean | null;
  /** `transcript` (extracted, quote checked by code) or `correction` (typed by a caregiver, no quote). */
  source?: "transcript" | "correction" | null;
  /** Where the quote is in the voice note (docs/contract.md, "Transcript segments"); null without audio times. */
  audio_start_sec?: number | null;
  audio_end_sec?: number | null;
};

export type NotificationRecipient = "caregiver" | "family";

/** One delivery of an emergency alert to one recipient on one channel (contract: "Emergency notifications"). */
export type AlertNotification = {
  to: NotificationRecipient;
  person_id: string | null;
  channel: "web";
  /** "skipped" = channel not active (old rows only). Not an error. */
  status: "sent" | "failed" | "skipped";
  error: string | null;
};

export type Alert = {
  id?: number;
  type: "omission" | "change" | "missing_item" | "emergency";
  item?: ChecklistItem | null;
  detail: string;
  plan_ref?: string | null;
  report_refs?: string[];
  evidence_quote?: string | null;
  evidence_verified?: boolean | null;
  /** Only on "emergency" alerts; [] otherwise. */
  notifications?: AlertNotification[];
  report_id?: string;
  report_version?: number;
  created_at?: string;
};

export type Person = { id: string; display_name: string; role?: Role };

export type Triage = {
  status: "ok" | "failed";
  emergency: boolean;
  reason: string | null;
  quote: string | null;
  quote_verified: boolean | null;
};

export type Report = {
  id: string;
  version: number;
  created_at: string;
  kind?: "shift" | "emergency";
  channel?: "web" | "seed";
  sender?: Person;
  /** Compatibility alias of `sender`. */
  caregiver: Person;
  transcript: string;
  audio_url: string | null;
  audio_duration_sec?: number | null;
  items: ReportItem[];
  missing_items: ChecklistItem[];
  alerts: Alert[];
  red_flag: boolean;
  red_flag_quote?: string | null;
  triage?: Triage | null;
  confirmation_text?: string;
};

/** One entry of GET /reports/{id}/versions (oldest first). Previous versions are immutable. */
export type ReportVersion = {
  version: number;
  source: "original" | "correction";
  created_at: string;
  created_by: Person;
  items: ReportItem[];
  missing_items: ChecklistItem[];
  alerts: Alert[];
  confirmation_text?: string;
};

/** Web inbox row from GET /me/notifications. */
export type AppNotification = {
  id: string;
  patient_id: string;
  patient_display_name: string;
  alert_id: number | null;
  report_id: string | null;
  recipient: NotificationRecipient;
  channel: "web";
  status: "sent" | "failed" | "skipped";
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
};

export type Citation = {
  report_id: string;
  quote: string;
  // null when the report has no segments (typed) or the quote is not in them (docs/contract.md).
  audio_start_sec: number | null;
  audio_end_sec: number | null;
};

export type QueryResponse = {
  answer: string;
  citations: Citation[];
  confidence: "answered" | "unclear";
  note: string | null;
};

export type MyPatient = {
  id: string;
  display_name: string;
  location: string;
  role: Role;
  // null for memberships with role "patient": the patient never sees reports or alerts.
  last_report_at: string | null;
  open_alerts: number | null;
  red_flag: boolean | null;
  missing_report: boolean | null;
  /** Newest patient help request / red-flag message of the last 24 h; null for family and the patient. */
  patient_alarm: "help" | "emergency" | null;
};

export type Member = { user_id: string; name: string; role: Role };
export type Invite = { id: string; contact: string; role: Role; status: "pending" | "accepted" };

/** Body of `POST /patients`. Doses are sent exactly as typed; nothing is computed. */
export type NewPatient = {
  display_name: string;
  location: string | null;
  emergency_contact?: EmergencyContact | null;
  /** The patient's own cell (E.164): signing up with it joins this profile as the patient. */
  phone?: string | null;
  care_plan: { medications: Omit<Medication, "id">[]; indications: string[]; allergies: string[] };
};

export type PatientMessage = {
  id: string;
  kind: "feeling" | "help";
  text: string | null;
  red_flag: boolean;
  /** Triage reason, only when `red_flag` is true. */
  reason: string | null;
  created_at: string;
  seen_by: { user_id: string; name: string }[];
};

/** What `POST /patients/{id}/patient-messages` returns. `message_for_patient` is fixed text written by code. */
export type PatientMessageResult = {
  id: string;
  kind: "feeling" | "help";
  notified: string[];
  red_flag: boolean;
  message_for_patient: string;
};

export type Message = {
  id: string;
  from: { user_id: string; name: string; role: Role };
  text: string;
  created_at: string;
  /** Own message: someone else opened the thread since. Others': the viewer had seen it before this load. */
  read: boolean;
  /** Sent by the viewer. */
  mine: boolean;
};

/** What `POST /patients/{id}/reports` returns (`ProcessResult` in docs/contract.md). */
export type ProcessResult =
  | {
      status: "ok";
      report: { id: string; version: number };
      items: ReportItem[];
      missing_items: ChecklistItem[];
      alerts: Alert[];
      red_flag: boolean;
      triage: {
        status: "ok" | "failed";
        emergency: boolean;
        reason: string | null;
        quote: string | null;
        quote_verified: boolean | null;
      };
      confirmation_text: string;
    }
  | { status: "needs_retry" | "not_a_report" | "forbidden"; message: string };

export type Membership = { patient_id: string; display_name: string; role: Role };

/** GET /me/invites: invites addressed to the caller's own phone, accepted or declined in the app. */
export type MyInvite = {
  id: string;
  /** null for a `patient` invite without a profile yet: accepting creates it (CIA-48). */
  patient_id: string | null;
  patient_display_name: string | null;
  role: Role;
  invited_by: string | null;
  created_at: string;
};

/** GET /me */
export type Me = {
  id: string;
  display_name: string;
  phone_last4: string;
  memberships: Membership[];
  /** Global admin: lists people and assigns roles only (CIA-48). */
  is_admin: boolean;
  /** Caregivers only create patients (CIA-48). */
  can_add_patients: boolean;
};

/** POST /auth/signup and /auth/login */
export type CodeSent = { status: "code_sent"; phone_last4: string; expires_in_sec: number; resend_after_sec: number };

/** POST /auth/verify: signed in, or a new phone that still has to give its name. */
export type Verified =
  | { status: "signed_in"; user: { id: string; name: string }; is_admin: boolean; memberships: Membership[] }
  | { status: "profile_required" };

/** Name and optional email for a new phone, sent with the same code. */
export type NewProfile = { name: string; email?: string };

// --- Admin (CIA-48, CIA-58): people and their role only; no patients, never clinical data. ---

export type AdminRole = Role | "admin";

export type AdminPerson = {
  id: string;
  name: string;
  phone: string;
  is_admin: boolean;
  /** The person's role; null for an older account with no role and no patients. */
  role: Role | null;
};

export type AdminPreRegistration = {
  id: string;
  phone: string;
  role: AdminRole;
  created_at: string;
};

export type AdminPeople = {
  people: AdminPerson[];
  pre_registrations: AdminPreRegistration[];
};

/** `error.current` of an admin 409 `overwrite_required`. */
export type OverwriteCurrent =
  | AdminPerson
  | { person: AdminPerson }
  | { pre_registration: AdminPreRegistration };
