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

export type Patient = {
  id: string;
  display_name: string;
  location?: string;
  care_plan: CarePlan;
};

export type ReportItem = {
  item: ChecklistItem;
  value: string | null;
  /** Coarse category code uses to compare over time (e.g. appetite normal / low / none). Optional for display. */
  level?: string | null;
  quote: string | null;
  quote_verified: boolean | null;
};

export type NotificationRecipient = "health_provider" | "caregiver" | "family";

/** One delivery of an emergency alert to one recipient on one channel (contract: "Emergency notifications"). */
export type AlertNotification = {
  to: NotificationRecipient;
  person_id: string | null;
  channel: "web" | "whatsapp";
  /** "skipped" = channel not active (e.g. WhatsApp off). Not an error. */
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
  channel?: "whatsapp" | "web" | "seed";
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
  audio_start_sec: number;
  audio_end_sec: number;
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
};

export type Member = { user_id: string; name: string; role: Role };
export type Invite = { id: string; contact: string; role: Role; status: "pending" | "accepted" };

export type PatientMessage = {
  id: string;
  kind: "feeling" | "help";
  text: string | null;
  created_at: string;
  seen_by: { user_id: string; name: string }[];
};

export type Message = {
  id: string;
  from: { user_id: string; name: string; role: Role };
  text: string;
  created_at: string;
  read: boolean;
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
