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

export type Alert = {
  type: "omission" | "change" | "missing_item" | "emergency";
  detail: string;
  plan_ref?: string;
  report_refs?: string[];
  evidence_quote?: string | null;
};

export type Report = {
  id: string;
  version: number;
  created_at: string;
  caregiver: { id: string; display_name: string };
  transcript: string;
  audio_url: string;
  audio_duration_sec?: number;
  items: ReportItem[];
  missing_items: ChecklistItem[];
  alerts: Alert[];
  red_flag: boolean;
  red_flag_quote?: string | null;
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
