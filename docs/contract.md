# Contract

Source of truth for integration between backend, web and input layers. Change it only in the same commit as the code that changes.

## General

- **Errors**: every error is `{ "error": { "code": "string", "message": "human-readable" } }`. Messages are in Spanish and safe to show as is. Validation errors (bad query or body) are `422` with code `invalid_request` and a fixed message; submitted values are never echoed back.
- **Timestamps**: all timestamps are ISO 8601 with an offset. The API returns UTC (`2026-10-18T00:05:00Z`). Naive values from the database are read as UTC. Clients display them in the reader's timezone (`APP_TIMEZONE` on the server, default `America/Argentina/Buenos_Aires`, is used for the time inside notification text).
- **Identity**: the caller is identified by the `cercania_session` cookie from `POST /auth/verify` (see "Auth"); without a valid one every call gets `401 unauthenticated`. Backend dev fallback only (SIMULATED, never in a deploy): with `ALLOW_DEV_IDENTITY_HEADER=1` an `X-Person-Id` header is also accepted, for curl and tests; the web app never sends it. Allowed CORS origins come from `WEB_ORIGINS`, with credentials and the `Content-Type` and `X-Person-Id` headers.
- **Access**: a person's role is per patient (`patient_access`). Permissions are in `ROLE_PERMISSIONS` in `backend/app/models.py`. For a patient the caller has no access to, the API answers `404 not_found` (no existence leak). For a role that lacks the permission, it answers `403 forbidden`.

## Checklist items (fixed enum)

`appetite`, `sleep`, `urination`, `medication`, `mood`, `mobility`, `pain`, `incidents`

Edit this list only after validating with a caregiver contact. Update `AGENTS.md` section 4 as well.

## Core function

```
process_report(patient_id, sender_id, transcript, audio_ref, message_id, segments=[]) -> ProcessResult
```

Implemented in `backend/app/process.py` (the entry point is reached through `app/ingest.py`). `sender_id` is a caregiver for shift reports; any registered role can trigger an emergency report (`report.kind = "emergency"`, no checklist items).

- Idempotent on `message_id`: a repeated delivery returns the stored result and creates nothing.
- Never raises to the caller for model errors. Caregiver reports that cannot be extracted return `status: "needs_retry"`.
- `audio_ref` is unused; channels pass `null`. The original voice note is stored by the channel after `process_report` returns (`ingest.store_audio`) and served through `GET /reports/{report_id}/audio`.
- `segments` are the transcript segments from transcription (see Transcript segments); `[]` for typed reports. They are stored on the report.

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
- `audio_start_sec` / `audio_end_sec` on items come from the report's transcript segments by the rule in Transcript segments, only for verified quotes; `null` when there are none, the quote is unverified or it is not in them.

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
    { "to": "family", "person_id": "fam_001", "channel": "web", "status": "sent", "error": null }
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
  "channel": "web",
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
- `channel` is `web` or `seed` (fixtures). Older rows may hold a retired value.
- `sender.role` is the sender's role for this patient. `caregiver` is a compatibility alias of `sender` for the web (`web/lib/types.ts`). Both are additive.
- `red_flag_quote` is the same value as `triage.quote`.
- `audio_url`: `/reports/{id}/audio` when the original voice note is stored, else `null` (typed reports, storage not configured, or a failed upload). It is an API path, not the file: call it (with the usual identity) to get a short-lived signed URL, then play that. `audio_duration_sec` is the voice note's length in seconds from transcription, or `null` (when a retry with the same `client_id` re-attaches the audio of a report whose first upload failed, it is the end of the report's last transcript segment). A retry never attaches audio to a typed report.
- `triage` is `null` for seed fixtures, which never went through triage.

## Transcript segments

Timestamped pieces of the transcript, used to play the audio fragment behind a quote. Stored on `report.segments` (`backend/app/models.py`); not returned by the API. The web only sees the resulting `audio_start_sec` / `audio_end_sec` on items and citations.

```json
[
  { "start": 0.0, "end": 3.5, "text": "Anoche le di la medicación de las ocho." },
  { "start": 3.5, "end": 6.0, "text": "Comió poco en la cena." },
  { "start": 6.0, "end": 8.0, "text": "Durmió bien." }
]
```

- `start` / `end`: seconds (float) from the start of the audio file. `text` is trimmed. Pieces are in audio order.
- **Granularity:** one piece per **word** when the provider returns word timestamps (Groq Whisper `verbose_json`; the backend sends `timestamp_granularities[]` = `word` and `segment`, the default), otherwise the provider's segments. Whisper often returns a whole voice note as a single segment, so words are what let a citation play just the quoted words. Same shape and same rule either way.
- Typed reports have `[]`.
- **Quote -> audio times** (code only, `backend/app/segments.py`, same for items and citations): the shortest run of consecutive segments whose joined text contains the quote, with the same normalization as quote verification (case, accents, punctuation, whitespace; whole words). `audio_start_sec` is the first segment's `start`, `audio_end_sec` the last segment's `end`. If two runs are equally short, the first one wins. No match or no segments: both `null`.
- Example: with the segments above, `"comió poco en la cena"` -> `3.5`-`6.0`; `"las ocho. Comió poco"` -> `0.0`-`6.0`.
- The model never sees or returns times.

## Endpoints

### `GET /patients/{patient_id}`

Permission: `read_care_plan` (all roles). Errors: `401`, `404 not_found`.

```json
{
  "id": "pat_001",
  "display_name": "Rosa (fictional)",
  "location": "Room 12",
  "care_plan": {
    "medications": [
      { "id": "med_002", "name": "Example-med", "dose": "as prescribed", "times": ["08:00", "20:00"] }
    ],
    "indications": ["Encourage fluids", "Assist when walking"],
    "allergies": []
  },
  "emergency_contact": { "name": "Emergencias Residencia", "phone": "+59899123456" }
}
```

`emergency_contact` is the number the app offers to call when an emergency is shown (`null` when not set; the web then offers 911). Stored in the patient's `health_provider_name` / `health_provider_phone` columns. It is contact information: the server never calls or texts it. `care_plan` is the active plan (`null` if none). `location` is free text stored on the patient (`patient.location`) and is `null` when not set. The doctor edits the plan (new plan version); the edit endpoint is Pending.

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

### `GET /reports/{report_id}/audio`

Permission: `read_reports` on the report's patient. Returns a signed URL for the original voice note in the private bucket. Anyone holding the URL can play it until it expires, so the web asks for a fresh one each time it plays and never stores it.

```json
{ "url": "https://<project>.supabase.co/storage/v1/object/sign/media/reports/pat_001/rep_123.webm?token=…", "expires_in_sec": 300 }
```

- Voice notes are stored after the report (after the response), so `audio_url` can stay `null` for a moment after `POST /patients/{id}/reports` returns.
- Play a citation: fetch `url`, set it as the player's source, seek to `audio_start_sec`, stop at `audio_end_sec`.

Errors: `401`; `404 not_found` (unknown report, no access, or the report has no stored audio); `403 forbidden` (patient role); `502 audio_unavailable` (storage did not answer or is not configured; the message is safe to show and asks to retry).

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
- The author is the session user, never a field in the body. Only `caregiver` memberships can correct.
- Returns the **Report shape** with the new latest version.

Errors: `401`; `404 not_found`; `403 forbidden` (role is not caregiver); `409 not_correctable` (the report is an emergency or has no version to correct); `409 version_conflict` (two corrections raced for the same version; retry); `422 invalid_request` (unknown item, empty `corrections`).

### `POST /patients/{patient_id}/query`

Permission: `read_reports`. Cited answer over the patient's reports from the last 14 days (at most 30, newest first). Model: Groq `openai/gpt-oss-120b` by default (`QUERY_MODEL` overrides; `query.py`).

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
- `audio_start_sec` / `audio_end_sec` come from the report's transcript segments by the rule in Transcript segments; `null` when there are none or the quote is not in them.
- With no reports in the window, the answer is `unclear` with `citations: []` and no model call.

Errors: `401`; `404`; `403` (role without `read_reports`, i.e. patient); `422 invalid_request` (empty or too long question); `502 query_failed` (model unavailable, timed out, refused, or returned an unusable answer; the message is safe to show and asks to retry).

### `GET /me`

Any authenticated person. Errors: `401 unauthenticated`.

```json
{
  "id": "cg_001",
  "display_name": "Ana (fictional)",
  "phone_last4": "0000",
  "is_admin": false,
  "can_add_patients": true,
  "memberships": [
    { "patient_id": "pat_001", "display_name": "Rosa (fictional)", "role": "caregiver" }
  ]
}
```

`is_admin`: global admin (see Admin). `can_add_patients`: the caller may use `POST /patients` (caregivers only).

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
      "location": "Room 12",
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

`alert_id` and `report_id` are set for emergency notifications. For patient help requests and red-flag messages they are `null` and `patient_message_id` is set instead (see Patient messages); `recipient` is then `caregiver`, `doctor`, `nurse` or `institution`.

`unread_count` counts all unread web notifications of the caller, regardless of `since` and `limit`. The web polls this endpoint with `since` set to the newest `created_at` it has seen, about every 5 seconds. Errors: `401`, `422`.

### `POST /me/notifications/{notification_id}/read`

Marks one of the caller's web notifications as read. Returns the notification object above with `read_at` set. Errors: `401`; `404 not_found` (unknown, not the caller's, or not a web row).

### `POST /me/notifications/read-all`

Marks all of the caller's unread web notifications as read. Returns `{ "updated": 3 }`.

### Emergency notifications

Triggered when triage says emergency (AGENTS.md 4.2), from any registered sender. Dispatch is in `backend/app/notify.py`.

- **Reply first**: the sender gets the fixed emergency text (no checklist questions). Dispatch runs after the reply, as a background task of the web endpoint.
- **Recipients are decided in code** (`models.emergency_recipients`): every caregiver and family member with access to the patient. **Never** the patient, the doctor role, or the sender. The patient's emergency contact is stored as contact information only; it has no inbox, so it is not notified. The web shows a `tel:` call button to it (or to 911 when none is set) wherever an emergency is shown; nothing is called automatically.
- **Channel**: `web` only. A `sent` row per recipient, shown in the inbox (`GET /me/notifications`) and polled by the web. `failed` and `skipped` statuses exist for old rows; nothing writes them now.
- **Message**: title `Emergencia: <patient>`; body with the sender's name, the local time and the triage reason. No transcript and no clinical advice.
- **Idempotent**: recipients that already have a row for the alert are not notified again; dispatch returns all rows. Dispatch never raises.
- **Status meaning**: `sent` means the inbox row was written. Read receipts are `read_at` on the row.
- `alert.notifications` on the alert carries the summary `{ to, person_id, channel, status, error }` of all rows.

## Roles (fixed enum)

`caregiver`, `family`, `patient`, `doctor`, `nurse`, `institution`. `doctor`, `nurse` and `institution` share the "health team" permissions in `AGENTS.md` section 6. A role belongs to a membership (user + patient), not to the user. Only `doctor` edits the care plan after creation (each edit is a new plan version); `patient` never sees reports or alerts. Endpoints return `403` with error `code: "forbidden"` when the role lacks the permission (`ROLE_PERMISSIONS` in `backend/app/models.py`).

## Auth (6-digit code by SMS)

No passwords. The code goes out **by SMS** (Twilio, `backend/app/sms.py`); invites are seen and accepted in the app, and emergency notifications go to the web inbox. The phone number is the identity.

The web app keeps the session in a cookie (`cercania_session`) set by `POST /auth/verify` (`HttpOnly`; `Secure` and `SameSite` from `SESSION_COOKIE_SECURE` / `SESSION_COOKIE_SAMESITE`). The web and the API are on different sites (`onrender.com` is a public suffix), and browsers block cross-site cookies, so **the browser never calls the API host directly**: it calls `/api/*` on the web origin, which Next.js rewrites to the API (`web/next.config.ts`). The cookie is therefore first-party on the web origin, and the deploy uses `SameSite=Lax`. Server components read the cookie and forward it to the API as a `Cookie` header (`web/lib/api.ts`). The web sends people with no cookie, or whose call returns `401`, to `/login`. The cookie is persistent (`Max-Age` = `SESSION_TTL_DAYS`), so the same device stays logged in: `/` and `/login` check `GET /me` and send a logged-in person straight to their home; a cookie the API no longer accepts shows the login form. Sessions last `SESSION_TTL_DAYS` (default 30) and are stored hashed server-side. Every endpoint below except `/auth/*` requires the cookie and returns `401 { "error": { "code": "unauthenticated" } }` without it. (Local dev only: `ALLOW_DEV_IDENTITY_HEADER=1` also accepts an `X-Person-Id` header; simulated identity, never in a real deploy.)

### `POST /auth/signup`

```json
{ "name": "Ana Pérez (fictional)", "email": "ana@example.com", "phone": "+59899000000" }
```

`email` is optional. The person is created only when the code is verified.

### `POST /auth/login`

```json
{ "phone": "+59899000000" }
```

Both send a 6-digit code by SMS to the phone and reply (with `TWILIO_TRIAL_TEMPLATE` set, the code comes from Twilio's trial template and `expires_in_sec` is 300; see README "Simulated"):

```json
{ "status": "code_sent", "phone_last4": "0000", "expires_in_sec": 600, "resend_after_sec": 60 }
```

Errors: `phone_invalid` (400; must be E.164, spaces and dashes are ignored), `too_many_requests` (429; one code per phone per `resend_after_sec`, at most 5 per hour), `sms_unreachable` (502, sign-up only: the SMS could not be sent; check the number and try again). None of them is about whether the phone has an account.

Anti-enumeration: these two endpoints must not reveal whether a phone is registered. `POST /auth/login` returns the same `code_sent` body for an unknown phone and sends nothing (the rate limit counts it the same way); if the SMS to a registered phone fails, it is logged and the answer is still `code_sent`. `POST /auth/signup` for a phone that already has an account sends a normal login code instead of creating a second user (the stored name is kept); since sign-up always texts the phone, it can report `sms_unreachable` without leaking anything. The code screen says "si no te llega en un minuto, pedí otro código". Email is contact info only: it is not verified, not unique, and never grants access, so there is no `email_taken`.

### `POST /auth/verify`

```json
{ "phone": "+59899000000", "code": "470123" }
```

```json
{ "user": { "id": "usr_001", "name": "Ana Pérez (fictional)" }, "is_admin": false, "memberships": [ { "patient_id": "pat_001", "display_name": "Rosa (fictional)", "role": "caregiver" } ] }
```

Only the latest code sent to the phone is valid. Codes are single-use, expire after `LOGIN_CODE_TTL_MINUTES` (default 10), are stored as salted hashes, and lock after 5 wrong attempts. Errors: `code_invalid` (400), `code_expired` (400), `too_many_attempts` (429; ask for a new code). A code that is not 6 digits is `422 invalid_request`. Invites are matched only on the phone proven by the code, never on email, and stay pending until accepted in the app (`POST /me/invites/{invite_id}/accept`).

**Starting role of a new person** (the sign-up that creates the person; logging in again changes nothing), decided in code (`backend/app/roles.py`):
1. The phone has an **admin pre-registration**: that role is applied and the pre-registration is consumed. With a patient, that membership; `admin`, `is_admin = true`; a caregiver without a patient, no memberships but `can_add_patients = true`; `patient`, their own new patient profile.
2. Otherwise, the phone has a **pending invite** (family or patient): nothing is applied; the person accepts it in the app.
3. Otherwise the person signed up for themselves: they get **their own patient profile** (display name = their name, no care plan) and the `patient` role on it, so `memberships` has that one entry.

If a phone has both a pre-registration and an invite, the pre-registration applies and the invite stays pending.

### `POST /auth/logout`

Deletes the session server-side and clears the cookie. Returns `{ "status": "logged_out" }`.

## Patients and team

### `POST /patients`

```json
{
  "display_name": "Rosa (fictional)",
  "location": "Room 12",
  "care_plan": {
    "medications": [ { "name": "Example-med", "dose": "as prescribed", "times": ["08:00", "20:00"] } ],
    "indications": ["Encourage fluids"],
    "allergies": []
  }
}
```

`location` is optional free text and is `null` when not set. `emergency_contact` (`{ name, phone }`) is optional; the phone is normalized to E.164 like other phones. Returns `201` with the patient as in `GET /patients/{patient_id}`. Only caregivers may add a patient (`403 forbidden` otherwise): someone with a caregiver membership, or a caregiver an admin registered before assigning patients (`GET /me` `can_add_patients`). The creator becomes `caregiver` and sets the initial care plan (version 1); after that only a `doctor` can edit it. Doses are stored as entered; nothing is computed. Each medication needs `name` and `dose` (1-120 characters); `times` are `HH:MM`. `care_plan` may be omitted (empty plan). Errors: `401`; `422 invalid_request` (empty name, bad time, too long); `422 phone_invalid` (emergency contact phone without country code).

### `PATCH /patients/{patient_id}/emergency-contact`

Permission: `edit_emergency_contact` (**caregiver and doctor** only; other roles get `403 forbidden`). Body: `{ "name": "Emergencias Residencia", "phone": "+598 99 123 456" }` to set, or the JSON `null` to clear. Name 1-120 characters; the phone is normalized to E.164. Returns `200` with the patient as in `GET /patients/{patient_id}`. Errors: `401`, `403`, `404`, `422 invalid_request` (empty name, malformed body), `422 phone_invalid` (message in Spanish, same text as other phone errors).

### `DELETE /patients/{patient_id}`

Permission: `archive_patient` (**caregiver** only; other roles get `403 forbidden`). Removes the patient from the app as a **soft delete**: every membership, pending invite and pre-registration for it is deleted (the memberships it had are logged in `role_change` as `patient_archived`), and `patient.archived_at` is set. Reports, versions, alerts and messages stay stored as the evidence trail, but nobody can reach them any more (`404` for everyone, and the patient leaves every `GET /me/patients`). Admins can no longer assign roles on it. Returns `{ "status": "archived" }`. Errors: `401`, `403`, `404`.

### `GET /patients/{patient_id}/members`

```json
{ "members": [ { "user_id": "usr_001", "name": "Ana Pérez (fictional)", "role": "caregiver" } ], "invites": [ { "id": "inv_001", "contact": "+59899111111", "role": "family", "status": "pending" } ] }
```

Permission: `read_reports` (caregiver, family, health team; not the patient). `invites` lists only **pending** invites (accepted ones show up as members) and is filled only for roles that can invite (caregivers); for everyone else it is `[]`, so invited phone numbers are not shown to family or the health team. Errors: `401`, `404`, `403`.

### `POST /patients/{patient_id}/invites`

```json
{ "contact": "+59899111111", "role": "family" }
```

Invites are **family or patient** (`role`, default `family`); any other role is `422 invite_role`, because every other role is assigned by an admin. `patient` makes the invited person this patient's own login (one per patient: `409 patient_has_login` if it already has one). `contact` is a phone number (E.164); emails are rejected with `phone_invalid` because email ownership is never verified. The invited person sees the invite in the app (`GET /me/invites`) once they sign in with that phone, and the membership is created only when they accept it. Only `caregiver` memberships can invite (`403 forbidden` otherwise), matching `AGENTS.md` section 6. Health-team and family members cannot invite.

Returns the invite (`201`, same shape as in `members.invites`). Re-inviting a number that already has a pending invite for this patient returns `200` with the same invite. Nothing is sent outside the app: the invited person sees the invite when they sign in. Errors: `400 phone_invalid` (not E.164, or an email); `409 already_member` (that phone already has access to the patient); `409 patient_has_login`; `422 invite_role` (a role other than `family` or `patient`); `401`, `404`, `403`.

### `POST /invites`

Same invite with the patient in the body: `{ "contact": "+59899111111", "role": "patient", "patient_id": null }`. `family` **needs** a patient (`422 patient_required`), and the caller must be able to invite to it (caregiver of that patient). `patient` with a `patient_id` is the patient's own login, as above. **`patient` without a `patient_id`** invites someone who has no profile yet: only caregivers may send it (`403 forbidden`), and accepting it creates the person's patient profile with the inviting caregiver as its caregiver. Returns the invite (`201`, or `200` for a re-invite).

### `GET /me/invites`

Any authenticated person. Pending invites addressed to the caller's own phone (the one their session proved), newest first. The web shows them on "Mis pacientes" and on the patient's own view (a self-signed-up patient's only screen) with Aceptar / Rechazar, and polls this endpoint with the notifications (about every 5 s) to show a toast for an invite that arrives while the app is open. Errors: `401`.

```json
{ "invites": [ { "id": "inv_001", "patient_id": "pat_001", "patient_display_name": "Rosa (fictional)", "role": "family", "invited_by": "Ana Pérez (fictional)", "created_at": "2026-10-18T00:05:00Z" } ] }
```

`patient_id` and `patient_display_name` are `null` for a `patient` invite without a profile yet.

### `POST /me/invites/{invite_id}/accept`

Creates the membership with the invite's role, family or patient (if the caller is already a member, their current role is kept). For a `patient` invite without a patient, it first creates the caller's own patient profile and makes the inviting caregiver its caregiver; `patient_id` in the answer is that new profile and marks the invite `accepted`. For a `patient` invite to an existing patient, a caller who already has their own profile (self sign-up) gets it **merged**: if no one else has access to that profile and it has no reports, its patient messages (and their notifications) move to the invited patient and the old profile is archived as in `DELETE /patients/{patient_id}` (logged as `own_profile_merged`); otherwise both profiles stay. Returns the membership: `{ "patient_id": "pat_001", "display_name": "Rosa (fictional)", "role": "family" }`. Errors: `401`; `404 not_found` (unknown, addressed to another phone, or no longer pending).

### `POST /me/invites/{invite_id}/decline`

Deletes the invite, so the caregiver can invite the number again. Returns `{ "status": "declined" }`. Same errors as accept.

## Admin

A global admin (`person.is_admin`) lists people and assigns roles, **nothing else**: being admin opens no patient, report, alert, care-plan or message route (those still need a membership). Admins are set by hand in the database, from an `admin` pre-registration at sign-up, or by **another admin on an existing person** (`PUT /admin/people/{id}/admin`, or a confirmed `admin` pre-registration of a registered phone). Every admin route answers `403 forbidden` to non-admins, and every change is written to `role_change` (who, when, before, after). Implemented in `backend/app/api/admin.py` and `backend/app/roles.py`.

**Overwrite warning:** a change that would replace something that exists answers `409 overwrite_required` with the current state in `error.current`, and is applied only when the same request is sent again with `"confirm_overwrite": true`.

### `GET /admin/people`

```json
{
  "people": [
    { "id": "cg_001", "name": "Ana (fictional)", "phone": "+15550100001", "is_admin": false, "is_caregiver": false,
      "memberships": [ { "patient_id": "pat_001", "patient_name": "Rosa (fictional)", "role": "caregiver" } ] }
  ],
  "pre_registrations": [
    { "id": "pre_1", "phone": "+15550100099", "role": "caregiver", "patient_id": null, "patient_name": null, "created_at": "2026-10-18T08:00:00Z" }
  ],
  "patients": [ { "id": "pat_001", "display_name": "Rosa (fictional)" } ]
}
```

`patients` is names only, to pick from when assigning a role. `is_caregiver` = a caregiver registered before any patient was assigned.

### `PUT /admin/people/{person_id}/memberships/{patient_id}`

`{ "role": "nurse", "confirm_overwrite": false }`. Adds the membership, or changes it. Replacing a **different** role the person already has on that patient is a `409` whose `error.current` is the person (as in `people`). Returns the person. Errors: `404` (unknown person or patient), `409`, `422` (`admin` is not a membership role).

### `PUT /admin/people/{person_id}/admin`

`{ "confirm_overwrite": false }`. Another admin makes an existing person an admin. Always a `409` first, with the person in `error.current` (name and current roles); applied with `confirm_overwrite: true`. Their memberships do not change. Already admin: `200`, nothing changes. Returns the person. Errors: `404`, `409`. Removing admin is done by hand in the database.

### `DELETE /admin/people/{person_id}/memberships/{patient_id}`

Removes it. Returns the person. Errors: `404`.

### `POST /admin/pre-registrations`

`{ "phone": "+15550100099", "role": "caregiver", "patient_id": null, "confirm_overwrite": false }`. A role for a phone that has not signed up. **Nothing is sent**: the person signs up on their own and starts with this role (see `POST /auth/verify`). `role` is a membership role or `admin`. `patient_id` is **required** for family, doctor, nurse and institution (`422 patient_required`), **optional** for caregiver, and **not used** for `admin` and `patient` (`422 patient_not_used`).

- Phone of a **registered person**: `409` with `error.current.person`. Confirmed, the role is applied to that person now and the answer is `200 { "applied_to": <person> }` (`admin` makes them an admin; their memberships stay).
- Phone with a **pending pre-registration**: `409` with `error.current.pre_registration`. Confirmed, it is replaced (`200`).
- Otherwise: `201 { "pre_registration": {...} }`.

Errors also: `400 phone_invalid`, `404` (unknown patient).

### `PATCH /admin/pre-registrations/{id}` and `DELETE /admin/pre-registrations/{id}`

PATCH `{ "role": "...", "patient_id": ... }` edits a pending one (same patient rules); DELETE removes it. Errors: `404`.

## Reports from the web app

### `POST /patients/{patient_id}/reports`

The caregiver's report. Either JSON text or multipart audio:

```json
{ "client_id": "web_7f3c", "text": "Casi no comió nada en la cena…" }
```

Multipart: `client_id` + `audio` file (webm/ogg/m4a). Audio goes through the same transcription step. Returns `ProcessResult` exactly as `process_report`. Idempotent on `client_id`: the `message_id` passed to `process_report` is `web:<person_id>:<client_id>`, so one user's id can never match another user's report. If the result is an emergency (`red_flag: true`), dispatch of the emergency notifications is scheduled after the response.

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

A repeated `client_id` is not transcribed again; the stored report's result is returned.

## Patient messages

### `POST /patients/{patient_id}/patient-messages`

Permission: `send_patient_message` (the `patient` role, and caregivers testing the patient view). Implemented in `backend/app/patient_messages.py`.

```json
{ "kind": "feeling", "text": "me duele un poco la rodilla" }
```

```json
{ "kind": "help" }
```

`kind` is `feeling` or `help`. `feeling` accepts `text` (1-1000 characters) or multipart `kind=feeling` + `audio` (same formats and size limit as web reports). Response:

```json
{ "id": "pm_001", "kind": "help", "notified": ["usr_001", "usr_004"], "red_flag": false, "message_for_patient": "Ya avisamos a tu equipo. Si es una emergencia, llamá a emergencias." }
```

`help` is a fixed rule: notify every caregiver and health-team member (doctor, nurse, institution) of the patient immediately; the model is never involved. Never family, never the patient, never the sender (a caregiver testing). `notified` lists the person ids that got a web inbox notification (`GET /me/notifications`, with `patient_message_id` set and `alert_id` / `report_id` `null`), written before the response. Notification text is written by code and never includes the patient's words.

`feeling` goes through the same triage step as reports (`triage.py`, model decides `red_flag`): the `text` field, or for `audio` the transcript, before replying. Audio must never skip triage; if triage fails, the reply still includes the fixed emergency line; if transcription fails, return `transcription_failed` and the UI asks the patient to retry or type, always showing "si es una emergencia, llamá a emergencias". When `red_flag` is `true`, the team is notified as for `help` and `message_for_patient` is this fixed text written in code (the model only decides `red_flag`, never the wording):

```json
{ "id": "pm_002", "kind": "feeling", "notified": ["usr_001", "usr_004"], "red_flag": true, "message_for_patient": "Avisamos a tu equipo. Si es una emergencia, llamá a emergencias o a tu médico ahora." }
```

When `feeling` is not an emergency, nobody is notified and `message_for_patient` is "Gracias, tu equipo va a ver tu mensaje. Si es una emergencia, llamá a emergencias." If triage fails, it is "Gracias, tu equipo va a ver tu mensaje." plus the fixed triage-failed line, and the message is stored with its triage status.

Errors: `401`; `404 not_found` (unknown patient or no access); `403 forbidden` (role without `send_patient_message`); `400` `invalid_kind`, `text_missing`, `text_too_long`, `audio_missing`, `audio_empty`, `invalid_json`; `413 audio_too_large`; `415` `unsupported_audio`, `unsupported_media_type`; `502 transcription_failed` (message asks to retry or type and says to call emergency services).

### `GET /patients/{patient_id}/patient-messages`

Permission: `read_patient_messages` (caregivers, health team and the patient; not family). Query: `limit` (1-100, default 50). Latest first: `{ "messages": [ { "id", "kind", "text", "red_flag", "created_at", "seen_by": [ { "user_id", "name" } ] } ] }`. `text` is `null` for `help`.

A caregiver or health-team member listing the messages marks the listed ones as seen by them (`seen_by`, oldest first). The patient listing them does not.

## Family <-> health team messages (bonus)

### `GET /patients/{patient_id}/messages`

```json
{ "messages": [ { "id": "msg_001", "from": { "user_id": "usr_005", "name": "Marta (fictional)", "role": "family" }, "text": "…", "created_at": "2026-10-17T18:02:00Z", "read": true, "mine": false } ] }
```

The latest `limit` messages (default 100, max 200), **oldest first**. Listing marks the other people's messages as read by the caller. `read`: on the caller's own message, someone else has opened the thread since it was sent; on anyone else's, the caller had already seen it before this request (so the UI can mark new ones). `mine`: the caller sent it. The web polls this every few seconds.

### `POST /patients/{patient_id}/messages`

```json
{ "text": "Hola doctora…", "client_id": "b7c1…" }
```

`201` with the stored message (same shape as one item above). `text` is trimmed, 1-2000 chars; otherwise `422 invalid_request`. `client_id` (optional, up to 64 chars) is generated once per message by the client and reused on retry: a repeat with the same `client_id` returns the message already stored instead of a second copy; the same `client_id` already used for another patient is `409 client_id_conflict`.

Only `family` and health-team roles (`doctor`, `nurse`, `institution`); `caregiver` and `patient` get `403 forbidden`, no access `404`. Human-to-human: no model call. The UI always shows "not for emergencies".

## Seed data

`backend/app/seed.py` creates 2-3 fictional patients, each with a care plan, and fictional users (caregivers, one doctor, one nurse, family members, and one patient login; no `institution` user yet), each with a fictional `@example.com` email, plus a few days of history so that `change` alerts can be demonstrated. No real names or data.
