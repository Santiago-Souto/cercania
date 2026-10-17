# Contract

Source of truth for integration between backend, web and input layers. Change it only in the same commit as the code that changes. The web owner builds against fake data shaped exactly like this and must not wait for the backend.

## General

- **Errors**: every error is `{ "error": { "code": "string", "message": "human-readable" } }`. Messages are in Spanish and safe to show as is. Validation errors (bad query or body) are `422` with code `invalid_request` and a fixed message; submitted values are never echoed back.
- **Timestamps**: all timestamps are ISO 8601 with an offset. The API returns UTC (`2026-10-18T00:05:00Z`). Naive values from the database are read as UTC. Clients display them in the reader's timezone (`APP_TIMEZONE` on the server, default `America/Argentina/Buenos_Aires`, is used for the time inside notification text).
- **Identity (SIMULATED)**: the caller is identified by the `X-Person-Id` header. The header is honored only when `ALLOW_DEV_IDENTITY_HEADER=1`; otherwise every call gets `401 unauthenticated`. Real login (CIA-26/32) is Pending. Allowed CORS origins come from `WEB_ORIGINS`, with credentials and the `Content-Type` and `X-Person-Id` headers.
- **Access**: a person's role is per patient (`patient_access`). Permissions are in `ROLE_PERMISSIONS` in `backend/app/models.py`. For a patient the caller has no access to, the API answers `404 not_found` (no existence leak). For a role that lacks the permission, it answers `403 forbidden`.

## Checklist items (fixed enum)

`appetite`, `sleep`, `urination`, `medication`, `mood`, `mobility`, `pain`, `incidents`

Edit this list only after validating with a caregiver contact. Update `AGENTS.md` section 4 as well.

## Core function

```
process_report(patient_id, sender_id, transcript, audio_ref, message_id) -> ProcessResult
```

Implemented in `backend/app/process.py` (the entry point is reached through `app/ingest.py`). `sender_id` is a caregiver for shift reports; any registered role can trigger an emergency report (`report.kind = "emergency"`, no checklist items).

- Idempotent on `message_id`: a repeated delivery returns the stored result and creates nothing.
- Never raises to the caller for model errors. Caregiver reports that cannot be extracted return `status: "needs_retry"`.
- `audio_ref` is accepted but not stored yet; channels pass `null`.

### ProcessResult statuses

| `status` | Meaning | Stored? |
|---|---|---|
| `ok` | Report stored (or already stored for this `message_id`). Carries `report`, `items`, `missing_items`, `alerts`, `red_flag`, `triage`, `confirmation_text`. | yes |
| `needs_retry` | Caregiver report that extraction could not process and that is not an emergency. `message` tells the sender to try again. | no |
| `not_a_report` | Sender is not a caregiver and triage found no emergency. `message` explains that shift reports come from caregivers. | no |
| `forbidden` | Sender has no access to the patient. `message` says nothing was stored. | no |

`unclear` is not a `process_report` status; it is only a `confidence` value of the cited query.

```json
{
  "status": "ok",
  "report": { "id": "rep_123", "version": 1 },
  "items": [
    {
      "item": "appetite",
      "value": "ate little at dinner",
      "level": "low",
      "details": null,
      "quote": "casi no comio nada en la cena",
      "quote_verified": true,
      "audio_start_sec": null,
      "audio_end_sec": null,
      "source": "transcript"
    },
    {
      "item": "sleep",
      "value": null,
      "level": null,
      "details": null,
      "quote": null,
      "quote_verified": null,
      "audio_start_sec": null,
      "audio_end_sec": null,
      "source": null
    }
  ],
  "missing_items": ["sleep", "urination"],
  "alerts": [
    {
      "id": 41,
      "type": "omission",
      "item": "medication",
      "detail": "08:00: no se mencionó.",
      "plan_ref": "med_002",
      "evidence_quote": null,
      "evidence_verified": null,
      "report_refs": ["rep_123"],
      "notifications": [],
      "report_id": "rep_123",
      "report_version": 1,
      "created_at": "2026-10-18T00:05:02Z"
    }
  ],
  "red_flag": false,
  "triage": {
    "status": "ok",
    "emergency": false,
    "reason": null,
    "quote": null,
    "quote_verified": null
  },
  "confirmation_text": "Registré: apetito: casi no comió en la cena. No mencionaste: sueño, diuresis. Podés mandar otra nota."
}
```

`alerts` above shows one of several; `change` alerts carry `report_refs` of the previous shift reports they compare against.

Rules:
- `quote` must be a substring (after normalization: case, accents, punctuation, whitespace; whole words only) of `transcript`. If not, set `quote_verified: false` and do not use the value for alerts.
- `medication` items carry `details.doses`: `[{ "plan_ref": "med_002", "time": "08:00", "given": true | false | null, "quote": "…", "quote_verified": true }]`. Only medications and times in the active care plan are accepted; `given: null` means unclear.
- Items not mentioned: `value: null`, `quote: null`. Never infer.
- `level` is a coarse category used by code to compare over time. Allowed values: appetite `normal` / `low` / `none`; sleep `normal` / `poor`; urination `normal` / `low` / `none`; mood `normal` / `low` / `agitated` / `confused`; mobility `normal` / `reduced` / `none`; pain and incidents `none` / `present`. Medication has no level (see `details.doses`).
- `source` is `transcript` (extracted, quote checked by code) or `correction` (typed by a caregiver, no quote).
- `red_flag` is decided by the **model** in the triage step (`triage.py`), not by a phrase list. `red_flag == triage.emergency`. The reply text sent on an emergency is fixed in code.
- `triage.quote` is verified like any other quote, but `quote_verified: false` **never** turns an emergency off; it is only shown as unverified.
- `triage.status` is `ok` or `failed` (model error/timeout). On `failed`, `red_flag` is `false`, the report is still stored and the reply still includes the fixed emergency line.
- On an emergency, `confirmation_text` is the fixed emergency message and asks no checklist questions.
- `audio_start_sec` / `audio_end_sec` on items are `null` until transcript segment times are wired (see Pending in README).

## Alert types

| type | produced by | meaning |
|---|---|---|
| `omission` | compare.py vs care plan | scheduled medication/indication not mentioned, not given, or unclear |
| `change` | compare.py vs history | deviation from the patient's usual pattern |
| `missing_item` | compare.py vs checklist | checklist item not covered in this report |
| `emergency` | triage.py (model) | the message describes an emergency; carries `detail` (triage reason), `evidence_quote`, `evidence_verified` and `notifications` (see Emergency notifications) |

Alert JSON (also inside every report and version):

```json
{
  "id": 42,
  "type": "emergency",
  "item": null,
  "detail": "Caída con golpe en la cabeza.",
  "plan_ref": null,
  "evidence_quote": "se cayó en el baño",
  "evidence_verified": true,
  "report_refs": ["rep_124"],
  "notifications": [
    { "to": "family", "person_id": "fam_001", "channel": "web", "status": "sent", "error": null },
    { "to": "family", "person_id": "fam_001", "channel": "whatsapp", "status": "skipped", "error": "WhatsApp desactivado (NOTIFY_WHATSAPP=0)" }
  ],
  "report_id": "rep_124",
  "report_version": 1,
  "created_at": "2026-10-18T00:30:00Z"
}
```

`id` is an integer. `report_id` and `report_version` say which version the alert belongs to. `notifications` is the summary of the delivery rows (see Emergency notifications); it is `[]` for non-emergency alerts.

## Report shape

Used by `GET /patients/{id}/reports`, `GET /reports/{id}` and the corrections response. The report carries its **latest version**.

```json
{
  "id": "rep_123",
  "version": 1,
  "created_at": "2026-10-18T00:05:00Z",
  "kind": "shift",
  "channel": "whatsapp",
  "sender": { "id": "cg_001", "display_name": "Ana (fictional)", "role": "caregiver" },
  "caregiver": { "id": "cg_001", "display_name": "Ana (fictional)", "role": "caregiver" },
  "transcript": "…",
  "audio_url": null,
  "audio_duration_sec": null,
  "items": [],
  "missing_items": [],
  "alerts": [],
  "red_flag": false,
  "red_flag_quote": null,
  "triage": { "status": "ok", "emergency": false, "reason": null, "quote": null, "quote_verified": null },
  "confirmation_text": "…"
}
```

- `kind` is `shift` (caregiver report, has items) or `emergency` (raised by another role, `items` and `missing_items` are empty).
- `channel` is `whatsapp`, `web`, or `seed` (fixtures).
- `sender.role` is the sender's role for this patient. `caregiver` is a compatibility alias of `sender` for the web (`web/lib/types.ts`). Both are additive.
- `red_flag_quote` is the same value as `triage.quote`.
- `audio_url` and `audio_duration_sec`: **SIMULATED**. Audio is not stored yet, so both are `null` for new reports. A stored audio file returns `/media/{report_id}` as a placeholder path; no `/media` route exists yet.
- `triage` is `null` for seed fixtures, which never went through triage.

## Endpoints

### `GET /patients/{patient_id}`

Permission: `read_care_plan` (all roles). Errors: `401`, `404 not_found`.

```json
{
  "id": "pat_001",
  "display_name": "Rosa (fictional)",
  "location": null,
  "care_plan": {
    "medications": [
      { "id": "med_002", "name": "Example-med", "dose": "as prescribed", "times": ["08:00", "20:00"] }
    ],
    "indications": ["Encourage fluids", "Assist when walking"],
    "allergies": []
  }
}
```

`care_plan` is the active plan (`null` if none). `location` has no storage yet and is always `null`. The doctor edits the plan (new plan version); the edit endpoint is Pending.

### `GET /patients/{patient_id}/reports`

Permission: `read_reports` (caregiver, family, doctor). Query: `limit` (1-100, default 20), `before` (ISO datetime). Newest first; each report carries its latest version. Errors: `401`, `404`, `403`, `422 invalid_request`.

```json
{
  "reports": [ { "...": "Report shape above" } ],
  "next_before": "2026-10-17T20:10:00Z"
}
```

`next_before` is the `created_at` of the last report returned when more may exist; pass it as `before` for the next page. It is `null` on the last page.

### `GET /patients/{patient_id}/alerts`

Permission: `read_reports`. Query: `since` (ISO datetime; returns alerts created after it), `limit` (1-200, default 50). Alerts on the **latest version** of each of the patient's reports, newest first. Errors: `401`, `404`, `403`, `422`.

```json
{ "alerts": [ { "...": "Alert JSON above" } ] }
```

### `GET /reports/{report_id}`

Permission: `read_reports` on the report's patient. Returns the **latest version** in the Report shape. Errors: `401`, `404 not_found` (unknown report, or no access), `403 forbidden`.

### `GET /reports/{report_id}/versions`

Permission: `read_reports`. Returns all versions, oldest first. Previous versions are immutable.

```json
{
  "report_id": "rep_123",
  "versions": [
    {
      "version": 1,
      "source": "original",
      "created_at": "2026-10-18T00:05:00Z",
      "created_by": { "id": "cg_001", "display_name": "Ana (fictional)", "role": "caregiver" },
      "items": [],
      "missing_items": [],
      "alerts": [],
      "confirmation_text": "…"
    },
    {
      "version": 2,
      "source": "correction",
      "created_at": "2026-10-18T09:12:00Z",
      "created_by": { "id": "cg_001", "display_name": "Ana (fictional)", "role": "caregiver" },
      "items": [],
      "missing_items": [],
      "alerts": [],
      "confirmation_text": "…"
    }
  ]
}
```

`source` is `original` (first processing) or `correction`. Errors: `401`, `404`, `403`.

### `POST /reports/{report_id}/corrections`

Permission: `correct_report` (caregiver only). The author is the caller; there is no `by` field.

```json
{ "corrections": [ { "item": "appetite", "value": "ate normally" } ] }
```

- `corrections`: one or more `{ item, value }`. `item` must be a checklist item. `value` is a string; `null` or an empty string means "not mentioned". If an item appears twice, the last one wins.
- Creates a **new version** (`source: "correction"`, `created_by` = caller). The previous version is not modified.
- Corrected items have `source: "correction"` and no quote. Other items are carried over unchanged. Omission and missing-item alerts are recomputed; the emergency alert and the change alerts of items that were not corrected are carried over, with their notification log.
- Returns the **Report shape** with the new latest version.

Errors: `401`; `404 not_found`; `403 forbidden` (role is not caregiver); `409 not_correctable` (the report is an emergency or has no version to correct); `409 version_conflict` (two corrections raced for the same version; retry); `422 invalid_request` (unknown item, empty `corrections`).

### `POST /patients/{patient_id}/query`

Permission: `read_reports`. Cited answer over the patient's reports from the last 14 days (at most 30, newest first). Model: Sonnet (`query.py`).

```json
{ "question": "Did she take the evening medication yesterday?" }
```

`question` is trimmed; 1 to 500 characters.

```json
{
  "answer": "El reporte de ayer a las 21:05 no menciona la medicación de las 20:00.",
  "citations": [
    { "report_id": "rep_122", "quote": "…", "audio_start_sec": null, "audio_end_sec": null }
  ],
  "confidence": "answered",
  "note": null
}
```

- `confidence` is `answered` or `unclear`. If the records do not contain the answer, return `unclear` and say so; never guess.
- Every citation is checked in code: `report_id` must be one of the reports sent to the model and the quote must verify against that report's transcript. Unverified citations are dropped. An `answered` reply with no surviving citation becomes `unclear` with a note.
- `audio_start_sec` / `audio_end_sec` come from stored transcript segments; `null` when there are none or the quote spans several segments.
- With no reports in the window, the answer is `unclear` with `citations: []` and no model call.

Errors: `401`; `404`; `403` (role without `read_reports`, i.e. patient); `422 invalid_request` (empty or too long question); `502 query_failed` (model unavailable, timed out, refused, or returned an unusable answer; the message is safe to show and asks to retry).

### `GET /me`

Any authenticated person. Errors: `401 unauthenticated`.

```json
{
  "id": "cg_001",
  "display_name": "Ana (fictional)",
  "phone_last4": "0000",
  "memberships": [
    { "patient_id": "pat_001", "display_name": "Rosa (fictional)", "role": "caregiver" }
  ]
}
```

### `GET /me/patients`

Any authenticated person. One entry per membership, for the dashboard. Status fields come from reports:

- `last_report_at`: `created_at` of the patient's newest report, or `null`.
- `red_flag`: some report from the last 24 h has `red_flag`.
- `open_alerts`: count of `emergency`, `omission` and `change` alerts on the latest version of reports from the last 24 h (`missing_item` alerts are not counted).
- `missing_report`: no report in the last 24 h.
- Role `patient` never sees reports or alerts: `last_report_at`, `open_alerts`, `red_flag` and `missing_report` are all `null`.

```json
{
  "patients": [
    {
      "id": "pat_001",
      "display_name": "Rosa (fictional)",
      "location": null,
      "role": "family",
      "last_report_at": "2026-10-18T00:05:00Z",
      "open_alerts": 1,
      "red_flag": false,
      "missing_report": false
    }
  ]
}
```

### `GET /me/notifications`

Any authenticated person. The caller's own **web** notifications only. Query: `since` (ISO datetime; returns rows created after it), `unread_only` (bool, default `false`), `limit` (1-200, default 50). Newest first.

```json
{
  "notifications": [
    {
      "id": "ntf_9a1c",
      "patient_id": "pat_001",
      "patient_display_name": "Rosa (fictional)",
      "alert_id": 42,
      "report_id": "rep_124",
      "recipient": "family",
      "channel": "web",
      "status": "sent",
      "title": "Emergencia: Rosa (fictional)",
      "body": "Ana (fictional) reportó una emergencia a las 21:30. Motivo: caída. Abrí CercanIA para ver el reporte.",
      "created_at": "2026-10-18T00:30:01Z",
      "read_at": null
    }
  ],
  "unread_count": 1
}
```

`unread_count` counts all unread web notifications of the caller, regardless of `since` and `limit`. The web polls this endpoint with `since` set to the newest `created_at` it has seen, about every 5 seconds. Errors: `401`, `422`.

### `POST /me/notifications/{notification_id}/read`

Marks one of the caller's web notifications as read. Returns the notification object above with `read_at` set. Errors: `401`; `404 not_found` (unknown, not the caller's, or not a web row).

### `POST /me/notifications/read-all`

Marks all of the caller's unread web notifications as read. Returns `{ "updated": 3 }`.

### Emergency notifications

Triggered when triage says emergency (AGENTS.md 4.2), from any registered sender. Dispatch is in `backend/app/notify.py`.

- **Reply first**: the sender gets the fixed emergency text (no checklist questions). Dispatch runs after the reply: as a background task for the web endpoint, right after the send for WhatsApp.
- **Recipients are decided in code** (`models.emergency_recipients`): the patient's registered health provider (if a phone is set; no web row), then every caregiver and family member with access to the patient. **Never** the patient, the doctor role, or the sender.
- **Channels**:
  - `web` is the primary channel: a `sent` row per recipient with a `person_id`, shown in the inbox (`GET /me/notifications`) and polled by the web.
  - `whatsapp` is attempted for every recipient only when `NOTIFY_WHATSAPP=1`. Otherwise each attempt is recorded as `skipped` with the error `WhatsApp desactivado (NOTIFY_WHATSAPP=0)`. A failed send is `failed` with the error text; never silent.
  - **Template fallback**: if Meta answers error `131047` (outside the 24 h window), and `WHATSAPP_EMERGENCY_TEMPLATE` is set, the same recipient gets that approved template (no parameters, language `WHATSAPP_TEMPLATE_LANG`, default `es`). If that also fails, the row is `failed`.
- **Message**: title `Emergencia: <patient>`; body with the sender's name, the local time and the triage reason. No transcript and no clinical advice.
- **Idempotent**: if the alert already has notification rows, dispatch sends nothing and returns them. Dispatch never raises.
- **Status meaning**: `sent` for WhatsApp means Meta accepted the request. Delivery receipts are not tracked yet.
- `alert.notifications` on the alert carries the summary `{ to, person_id, channel, status, error }` of all rows.

## Reports from the web app

### `POST /patients/{patient_id}/reports`

Same report a caregiver can send by WhatsApp. Either JSON text or multipart audio:

```json
{ "client_id": "web_7f3c", "text": "Casi no comió nada en la cena…" }
```

Multipart: `client_id` + `audio` file (webm/ogg/m4a). Audio goes through the same transcription step. Returns `ProcessResult` exactly as `process_report`. Idempotent on `client_id`: the `message_id` passed to `process_report` is `web:<person_id>:<client_id>`, so one user's id can never match another user's report or a WhatsApp message. If the result is an emergency (`red_flag: true`), dispatch of the emergency notifications is scheduled after the response.

Requires the `send_report` permission for that patient (today only `caregiver`). Errors, all as `{ "error": { "code", "message" } }` with a message the UI can show as is:

| HTTP | `code` | When |
|---|---|---|
| 400 | `client_id_missing`, `text_missing`, `audio_missing`, `audio_empty`, `invalid_json` | Bad input |
| 401 | `unauthenticated` | No caller identity |
| 403 | `forbidden` | Role lacks `send_report` for this patient |
| 404 | `not_found` | Unknown patient |
| 409 | `client_id_conflict` | Same `client_id` already used by this user for another patient |
| 413 | `audio_too_large` | Audio over 4 MB (Vercel caps request bodies at 4.5 MB) |
| 415 | `unsupported_audio`, `unsupported_media_type` | Not webm/ogg/m4a/mp3/wav, or neither JSON nor multipart |
| 422 | `invalid_request` | Invalid body (validation) |
| 502 | `transcription_failed` | Transcription failed; ask to retry or type |
| 503 | `processing_unavailable` | `process_report` cannot be imported; nothing was stored (not expected on the current code) |

A repeated `client_id` is not transcribed again; the stored report's result is returned.

### Magic link (Pending)

Not built: there is no `POST /auth/link` route yet. Planned: a user who messages the bot gets a single-use URL that expires after `MAGIC_LINK_TTL_MINUTES`. Roles: `caregiver`, `family` (read-only), `doctor` (only role that edits the care plan), `patient` (own profile and care plan; no reports or alerts). A role is per patient.

## Webhook and WhatsApp

### `GET /webhook/whatsapp`

Meta Cloud API verification handshake. Query `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`. Returns the challenge as plain text when the token matches `WHATSAPP_VERIFY_TOKEN`, else 403 `verification_failed`.

### `POST /webhook/whatsapp`

Meta Cloud API webhook (JSON). Requests without a valid `X-Hub-Signature-256` (HMAC-SHA256 of the body with `WHATSAPP_APP_SECRET`) get 403 `invalid_signature`. Response on success: `{ "status": "received" }`. Status updates (delivered/read) are acked and ignored. Voice notes are transcribed; text messages are treated as a typed report; other types get a reply asking for a voice note.

The handler acknowledges immediately (HTTP 200) and processes each new message in the background. Duplicate deliveries are ignored by message id (in memory). The sender is identified by phone number and routed by role (AGENTS.md §4.1).

**Routing, as the code does it today:**
- Caregivers' messages go through `process_report` (triage and extraction). The emergency reply goes out after `process_report` returns, not before extraction.
- Family, doctor and patient messages do **not** reach triage yet. The bot only looks at patients where the sender has `send_report` (caregiver only), so a registered non-caregiver with no caregiver assignment gets the "no patients assigned" reply and nothing is stored. The `process_report` branches for non-caregivers (`not_a_report`, emergency report) exist but are not reachable from WhatsApp yet. Target (AGENTS.md 4.1): every registered sender's message goes through triage, with the emergency reply first.

Bot behavior (all replies are WhatsApp text):
- Sender phone not in `person.phone` → "number not registered" message, which always includes the fixed emergency line; nothing processed, no model call.
- No patient where the sender has `send_report` → "no patients assigned" message. This is where family, doctor and patient messages stop today.
- Several patients → numbered "¿De qué paciente es el reporte?" question; the report is kept (in memory, 30 min) and processed once the caregiver answers with the number or part of the name. `message_id` is the report's id, not the answer's.
- Reports sent while a choice is pending (voice, or typed text of 4+ words) are queued, never dropped: the bot says it kept them and asks about each in arrival order. Reports that expire without a choice are announced on the caregiver's next message so they can resend them.
- After `process_report`: `confirmation_text` (or the result's `message` for `needs_retry` / `not_a_report` / `forbidden`). When `red_flag` is true, a fixed line written in code is prepended: "⚠️ Si es una emergencia, llamá a emergencias o al médico ahora." Then the emergency notifications are dispatched.
- If `process_report` cannot be imported, the caregiver is told nothing was stored.

## Seed data

`backend/app/seed.py` creates 2-3 fictional patients, each with a care plan, one caregiver, one family member, and a few days of history so that `change` alerts can be demonstrated. Seeded reports have `channel: "seed"` and `triage: null`. No real names or data.
